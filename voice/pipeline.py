"""
The real-time voice pipeline for one call:

    browser mic --WebRTC--> STT (Sarvam) -> language tap -> user turn (Silero VAD)
      -> agent bridge (LangGraph + Nova) -> TTS (Sarvam) --WebRTC--> browser speaker

Pipecat does the hard real-time parts: voice activity detection, deciding
when the caller has finished a turn, and barge-in (when the caller talks
over the bot, the bot stops and the pending reply is cancelled).

Each call is limited in length and ends after a stretch of silence, so an
abandoned tab cannot keep paying for speech services.
"""
import asyncio
import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    EndWorkerFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    MetricsFrame,
    TextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from agent.graph import Agent
from core.config import Settings
from core.session import CallSession

from .language import reply_language

log = logging.getLogger("vaani.voice")

GOODBYE_AT_LIMIT = "We have reached the time limit for a demo call. Thank you for calling Vaani. Goodbye!"


class LanguageTap(FrameProcessor):
    """Records the language STT detected for each final transcript."""

    def __init__(self, session: CallSession):
        super().__init__()
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            if frame.language:
                self.session.language = str(frame.language.value if hasattr(frame.language, "value") else frame.language)
            self.session.emit("heard", text=frame.text, language=self.session.language)
        await self.push_frame(frame, direction)


class AgentBridge(FrameProcessor):
    """
    Hands each finished caller turn to the LangGraph agent and streams the
    reply to TTS in the reply's language. If the caller interrupts, the
    pending reply is cancelled.
    """

    def __init__(self, session: CallSession, agent: Agent, tts_language: str = "hi-IN"):
        super().__init__()
        self.session, self.agent = session, agent
        self._tts_language = tts_language
        self._task: asyncio.Task | None = None
        session.on_interim = self._speak          # fillers while a lookup runs

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            text = _last_user_text(frame.context)
            if text:
                await self._cancel()
                self._task = self.create_task(self._respond(text))
            return
        if isinstance(frame, InterruptionFrame):
            await self._cancel()
        await self.push_frame(frame, direction)

    async def _cancel(self):
        if self._task and not self._task.done():
            await self.cancel_task(self._task)
        self._task = None

    async def _speak(self, text: str):
        """Send text to TTS in its own language (switching the voice's language if needed)."""
        lang = reply_language(text, self.session.language)
        if lang != self._tts_language:
            self._tts_language = lang
            await self.push_frame(TTSUpdateSettingsFrame(delta=SarvamTTSService.Settings(language=Language(lang))))
        await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(TextFrame(text))
        await self.push_frame(LLMFullResponseEndFrame())

    async def _respond(self, text: str):
        reply = await self.agent.turn(self.session, text)
        await self._speak(reply)
        if self.session.end_requested:
            await self.push_frame(EndWorkerFrame(reason="agent ended the call"))


class MetricsTap(FrameProcessor):
    """Forwards speech-service latency (time to first byte) to the browser panel."""

    def __init__(self, session: CallSession):
        super().__init__()
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            ttfb = {d.processor: round(d.value * 1000) for d in frame.data if isinstance(d, TTFBMetricsData)}
            if ttfb:
                self.session.emit("latency", ttfb_ms=ttfb)
        await self.push_frame(frame, direction)


def _last_user_text(context: LLMContext) -> str:
    for m in reversed(context.get_messages()):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c.strip()
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict)).strip()
    return ""


def build_worker(session: CallSession, connection: SmallWebRTCConnection, agent: Agent, settings: Settings) -> PipelineWorker:
    key = settings.sarvam_api_key.get_secret_value()
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    stt = SarvamSTTService(api_key=key, settings=SarvamSTTService.Settings(model=settings.sarvam_stt_model))
    tts_settings = dict(model=settings.sarvam_tts_model, voice=settings.sarvam_tts_voice,
                        language=Language.HI_IN, pace=settings.sarvam_tts_pace)
    if settings.sarvam_tts_model.startswith("bulbul:v3"):
        tts_settings["temperature"] = settings.sarvam_tts_temperature
    tts = SarvamTTSService(api_key=key, settings=SarvamTTSService.Settings(**tts_settings))
    context = LLMContext()
    turns = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.6))))

    pipeline = Pipeline([
        transport.input(), stt, LanguageTap(session), turns.user(),
        AgentBridge(session, agent), tts, transport.output(), turns.assistant(), MetricsTap(session),
    ])
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        idle_timeout_secs=settings.call_idle_seconds,
    )

    @transport.event_handler("on_client_connected")
    async def _connected(_transport, _client):
        session.emit("call", status="connected", mode="voice")
        await worker.queue_frames([TTSSpeakFrame(session.greeting or agent.greet(session))])

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport, _client):
        await worker.cancel(reason="caller hung up")

    return worker


async def run_call(session: CallSession, connection: SmallWebRTCConnection, agent: Agent, settings: Settings, on_done) -> None:
    """Run one voice call to the end, with a hard time limit. `on_done` always runs."""
    worker = build_worker(session, connection, agent, settings)
    runner = WorkerRunner(handle_sigint=False)
    session.voice_active = True

    async def time_limit():
        await asyncio.sleep(settings.call_max_seconds)
        session.emit("call", status="time_limit")
        await worker.queue_frames([TTSSpeakFrame(GOODBYE_AT_LIMIT), EndWorkerFrame(reason="time limit")])

    limiter = asyncio.create_task(time_limit())
    try:
        await runner.run(worker)
    except Exception as e:                       # a speech-service outage must not crash the server
        log.warning("voice call %s failed: %s", session.id, type(e).__name__)
        session.emit("error", message="The voice connection failed. You can switch to text mode.")
    finally:
        limiter.cancel()
        session.voice_active = False
        await on_done(session)
