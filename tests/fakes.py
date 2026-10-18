"""A stand-in for Nova: replays scripted steps so the agent loop can be tested offline."""
import itertools
from collections.abc import Callable

from langchain_core.messages import AIMessage

_ids = itertools.count(1)


def call(name: str, **args) -> AIMessage:
    """A model step that calls one tool."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}", "type": "tool_call"}])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


class ScriptedModel:
    """
    Each step is an AIMessage or a function(messages, tool_names) -> AIMessage.
    Records the tool names it was offered at every step, for access tests.
    """

    def __init__(self, steps: list):
        self.steps = list(steps)
        self.offered: list[list[str]] = []
        self._bound: list[str] = []

    def bind_tools(self, schemas: list[dict]):
        bound = ScriptedModel.__new__(ScriptedModel)
        bound.__dict__ = self.__dict__
        bound._bound_now = [s["function"]["name"] for s in schemas]
        return bound

    async def ainvoke(self, messages):
        self.offered.append(getattr(self, "_bound_now", []))
        if not self.steps:
            return say("(script finished)")
        step = self.steps.pop(0)
        if isinstance(step, Callable):
            step = step(messages, self.offered[-1])
        return step
