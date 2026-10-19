"""
The agent: a LangGraph loop of Nova and tools.

    START -> gate -> model -> tools -> gate -> model -> ... -> END

  gate   works out which tools this caller may use right now (before or
         after verification, staff role) and refreshes the system prompt.
  model  Nova, bound to only those tools.
  tools  runs the calls Nova asked for; each tool checks access again.

The loop is capped (recursion limit, tool calls per step, turns per call)
so a confused model cannot loop or run up costs. A last check on the reply
stops internal notes from ever being spoken to a customer, even if the
model ignores its instructions.
"""
import asyncio
import json
import logging
import time
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from core.config import Settings
from core.session import CallSession
from core.store import Store

from . import tools as T
from .persona import LOOKUP_TOOLS, filler, fix_self_gender, speakable, voice_gender
from .prompts import system_prompt

log = logging.getLogger("vaani.agent")

MAX_TOOL_CALLS_PER_STEP = 4
RECURSION_LIMIT = 16            # graph steps per caller turn (about 5 model calls)
HISTORY_MESSAGES = 40

FALLBACK = {
    "hi": "माफ़ कीजिए, अभी थोड़ी दिक्कत आ रही है। कृपया एक बार फिर से बोलिए।",
    "mr": "माफ करा, आत्ता थोडी अडचण येत आहे. कृपया पुन्हा सांगा.",
    "ta": "மன்னிக்கவும், இப்போது ஒரு சிக்கல் உள்ளது. தயவுசெய்து மீண்டும் சொல்லுங்கள்.",
    "en": "Sorry, I'm having trouble right now. Could you say that again, please?",
}
LIMIT_REACHED = {
    "hi": "यह डेमो कॉल अपनी सीमा तक पहुँच गई है। धन्यवाद!",
    "en": "This demo call has reached its limit. Thank you for calling!",
}
BLOCKED = {
    "hi": "माफ़ कीजिए, मैं यह जानकारी साझा नहीं कर सकती। मैं आपके लिए कॉलबैक बुक कर सकती हूँ।",
    "en": "Sorry, I can't share that. I can book a callback from our team if you like.",
}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tool_names: list[str]


def _lang(session: CallSession) -> str:
    return (session.language or "en")[:2]


class Agent:
    def __init__(self, model: Any, store: Store, settings: Settings):
        self.model, self.store, self.settings = model, store, settings
        self.gender = settings.assistant_gender or voice_gender(settings.sarvam_tts_voice)
        g = StateGraph(State)
        g.add_node("gate", self._gate)
        g.add_node("model", self._call_model)
        g.add_node("tools", self._run_tools)
        g.add_edge(START, "gate")
        g.add_edge("gate", "model")
        g.add_conditional_edges("model", self._route, {"tools": "tools", END: END})
        g.add_edge("tools", "gate")
        self.graph = g.compile()

    # ---- nodes ---------------------------------------------------------------

    def _gate(self, state: State, config) -> dict:
        session: CallSession = config["configurable"]["session"]
        names = [t.name for t in T.available(session)]
        session.emit("node", name="gate", tools=names)
        return {"tool_names": names}

    async def _call_model(self, state: State, config) -> dict:
        session: CallSession = config["configurable"]["session"]
        specs = [T.REGISTRY[n] for n in state["tool_names"]]
        model = self.model.bind_tools([s.schema() for s in specs]) if specs else self.model
        messages = [SystemMessage(system_prompt(session, self.store, self.gender))] + [
            m for m in state["messages"] if not isinstance(m, SystemMessage)]
        started = time.perf_counter()
        response: AIMessage = await model.ainvoke(messages)
        session.emit("node", name="model", ms=round((time.perf_counter() - started) * 1000),
                     tool_calls=[c["name"] for c in response.tool_calls])
        if len(response.tool_calls) > MAX_TOOL_CALLS_PER_STEP:
            response.tool_calls = response.tool_calls[:MAX_TOOL_CALLS_PER_STEP]
        await self._interim(session, response)
        return {"messages": [response]}

    async def _interim(self, session: CallSession, response: AIMessage) -> None:
        """
        While a lookup runs, say something short so the caller isn't left in
        silence: what the model said alongside its tool call, or a filler.
        Once per caller turn, and only on a voice call (the hook is set there).
        """
        hook = session.on_interim
        if hook is None or session.interim_said or not response.tool_calls:
            return
        if not any(c["name"] in LOOKUP_TOOLS for c in response.tool_calls):
            return
        text = speakable(_text_of(response)) or filler(session.language, self.gender)
        session.interim_said = True
        text = fix_self_gender(text, self.gender)
        session.emit("transcript", role="bot", text=text)
        try:
            await hook(text)
        except Exception:                                # never let a filler break the turn
            log.debug("interim speech failed", exc_info=True)

    async def _run_tools(self, state: State, config) -> dict:
        session: CallSession = config["configurable"]["session"]
        ctx = T.ToolContext(session, self.store, self.settings)
        last: AIMessage = state["messages"][-1]
        out = []
        for call in last.tool_calls:
            # tools are quick and CPU-bound; a thread keeps the audio loop responsive
            result = await asyncio.to_thread(T.execute, ctx, call["name"], call.get("args") or {})
            out.append(ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call["id"]))
        return {"messages": out}

    @staticmethod
    def _route(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    # ---- one caller turn -------------------------------------------------------

    async def turn(self, session: CallSession, text: str) -> str:
        """Run one caller turn and return what to say. Never raises."""
        async with session.turn_lock:
            lang = _lang(session)
            session.turns += 1
            session.interim_said = False
            session.emit("transcript", role="user", text=text, language=session.language)
            if session.turns > self.settings.max_turns_per_call:
                session.end_requested = True
                return self._say(session, LIMIT_REACHED.get(lang, LIMIT_REACHED["en"]))
            history = _trim(session.history)
            prior = len(history)
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    self.graph.ainvoke({"messages": history + [HumanMessage(text)], "tool_names": []},
                                       config={"configurable": {"session": session}, "recursion_limit": RECURSION_LIMIT}),
                    timeout=self.settings.llm_timeout_seconds * 3,
                )
            except Exception as e:                      # throttling, timeouts, recursion limit, model errors
                log.warning("agent turn failed in session %s: %s", session.id, type(e).__name__)
                session.emit("error", message="The assistant could not answer this turn.", kind=type(e).__name__)
                return self._say(session, FALLBACK.get(lang, FALLBACK["en"]))
            new = result["messages"][prior:]
            session.history = history + new
            reply = _text_of(new[-1]) if new else ""
            session.emit("latency", agent_ms=round((time.perf_counter() - started) * 1000))
            reply = speakable(self._guard(session, reply))
            return self._say(session, reply or FALLBACK.get(lang, FALLBACK["en"]))

    def _say(self, session: CallSession, text: str) -> str:
        text = fix_self_gender(text, self.gender)
        session.emit("transcript", role="bot", text=text)
        return text

    def _guard(self, session: CallSession, reply: str) -> str:
        """Last line of defence: a customer never hears an internal note."""
        if session.line != "customer":
            return reply
        lowered = reply.lower()
        notes = [l["internal_note"] for l in self.store.loans.values() if l["internal_note"]]
        if any(n.lower() in lowered for n in notes if len(n) > 12) or "internal note" in lowered:
            session.emit("guard", blocked="internal note in reply")
            return BLOCKED.get(_lang(session), BLOCKED["en"])
        return reply


def _text_of(message: AnyMessage) -> str:
    content = message.content
    text = content if isinstance(content, str) else " ".join(
        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type", "text") == "text")
    return " ".join(text.split())


def _trim(history: list[AnyMessage]) -> list[AnyMessage]:
    """Keep recent history, cut at a caller turn so tool calls and results stay paired."""
    if len(history) <= HISTORY_MESSAGES:
        return list(history)
    start = len(history) - HISTORY_MESSAGES
    while start < len(history) and not isinstance(history[start], HumanMessage):
        start += 1
    return history[start:]
