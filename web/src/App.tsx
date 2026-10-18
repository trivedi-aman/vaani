import { useCallback, useEffect, useRef, useState } from "react";
import { accessCode, api, ApiError, streamEvents, type CallHandle } from "./api";
import { Inside } from "./components/Inside";
import { Phone, type Bubble, type Mode, type Phase } from "./components/Phone";
import { ScenarioDrawer } from "./components/ScenarioDrawer";
import { spokenDigits } from "./score";
import type { CallEvent, Config, Line, Scenario } from "./types";
import type { VoiceCall } from "./voice";

type View = "scenario" | "phone" | "inside";

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [needCode, setNeedCode] = useState(false);
  const [codeRejected, setCodeRejected] = useState(false);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [loadError, setLoadError] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [line, setLine] = useState<Line | null>(null);
  const [mode, setMode] = useState<Mode>("text");
  const [events, setEvents] = useState<CallEvent[]>([]);
  const [otp, setOtp] = useState<{ code: string; to: string } | null>(null);
  const [lastOtp, setLastOtp] = useState("");
  const [speaking, setSpeaking] = useState<"user" | "bot" | null>(null);
  const [muted, setMuted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [view, setView] = useState<View>("phone");

  const call = useRef<CallHandle | null>(null);
  const voice = useRef<VoiceCall | null>(null);
  const closeStream = useRef<(() => void) | null>(null);

  const load = useCallback(async () => {
    try {
      const cfg = await api.config();
      setConfig(cfg);
      if (cfg.access_code_required && !accessCode.get()) {
        setNeedCode(true);
        return;
      }
      setScenarios(await api.scenarios());
      setNeedCode(false);
      setCodeRejected(false);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 429)) {
        const tried = !!accessCode.get();
        accessCode.clear();
        setNeedCode(true);
        setCodeRejected(tried);
      } else {
        setLoadError(e instanceof Error ? e.message : "Could not reach the server.");
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onEvent = useCallback((e: CallEvent) => {
    setEvents((prev) => [...prev, e]);
    if (e.type === "otp") {
      setOtp({ code: e.code, to: e.to });
      setLastOtp(e.code);
    }
    if (e.type === "call" && e.status === "connected") {
      setPhase("incall");
      setStartedAt(Date.now());
      setStatus("");
    }
    if (e.type === "call" && e.status === "ended") {
      setPhase("ended");
      setSpeaking(null);
    }
    if (e.type === "error") setStatus(e.message);
    if (e.type === "state" && e.locked) setStatus("Verification is locked for this call.");
  }, []);

  const dial = async (l: Line, m: Mode) => {
    setEvents([]);
    setOtp(null);
    setLastOtp("");
    setStatus("");
    setLine(l);
    setMode(m);
    setPhase("connecting");
    try {
      const handle = await api.startCall(l, scenario?.line === l ? scenario.id : undefined);
      call.current = handle;
      closeStream.current = streamEvents(handle, onEvent, () => undefined);
      if (m === "voice") {
        const { startVoice } = await import("./voice");   // the WebRTC client loads only for voice calls
        voice.current = await startVoice(handle, config?.ice_servers ?? [], {
          onSpeaking: setSpeaking,
          onEnded: () => setPhase("ended"),
          onError: setStatus,
        });
      } else {
        setPhase("incall");
        setStartedAt(Date.now());
      }
    } catch (e) {
      setPhase("ended");
      if (e instanceof ApiError && e.status === 403) {
        accessCode.clear();
        setNeedCode(true);
      }
      const msg = e instanceof Error ? e.message : String(e);
      setStatus(/permission|NotAllowed/i.test(msg) ? "Microphone access was blocked. Allow it in the browser, or call by typing." : msg);
    }
  };

  const hangUp = async () => {
    const handle = call.current;
    try {
      await voice.current?.hangUp();
    } catch {
      /* already gone */
    }
    voice.current = null;
    if (handle) await api.hangUp(handle).catch(() => undefined);
    setPhase("ended");
  };

  const send = async (text: string) => {
    const handle = call.current;
    if (!handle) return;
    setBusy(true);
    setStatus("");
    try {
      const r = await api.say(handle, text);
      if (r.ended) setPhase("ended");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Could not send that.");
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    closeStream.current?.();
    closeStream.current = null;
    call.current = null;
    setPhase("idle");
    setLine(null);
    setOtp(null);
    setStartedAt(null);
  };

  useEffect(() => {
    if (!otp) return;
    const t = setTimeout(() => setOtp(null), 20_000);   // like a real SMS banner
    return () => clearTimeout(t);
  }, [otp]);

  useEffect(() => () => {
    void voice.current?.hangUp();
    closeStream.current?.();
  }, []);

  if (needCode) return <AccessGate onDone={load} rejected={codeRejected} />;

  const bubbles: Bubble[] = events.flatMap((e) => (e.type === "transcript" ? [{ role: e.role, text: e.text }] : []));
  const quickLines = scenario && line === scenario.line
    ? scenario.turns.map((t) => (t === "{otp}" ? (lastOtp ? spokenDigits(lastOtp, scenario.language) : "") : t)).filter(Boolean)
    : [];
  const inCall = phase === "connecting" || phase === "incall";

  return (
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <span className="logo" aria-hidden="true">V</span>
          <div>
            <h1>Vaani test bench</h1>
            <p>A voice agent for loan customers and staff that has to get names, dates and numbers right in Indian languages.</p>
          </div>
        </div>
        {config && <p className="demo-date">Demo data is as of {new Date(config.demo_today).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}</p>}
      </header>
      {loadError && <p className="banner" role="alert">{loadError} <button className="link" onClick={() => { setLoadError(""); void load(); }}>Try again</button></p>}

      <nav className="views" aria-label="Sections">
        {(["scenario", "phone", "inside"] as View[]).map((v) => (
          <button key={v} aria-current={view === v} onClick={() => setView(v)}>
            {v === "scenario" ? "Scenario" : v === "phone" ? "Phone" : "Under the hood"}
          </button>
        ))}
      </nav>

      <main className="bench" data-view={view}>
        <div className="col col-scenario">
          <ScenarioDrawer scenarios={scenarios} selected={scenario} onSelect={setScenario} disabled={inCall} />
        </div>
        <div className="col col-phone">
          <Phone
            phase={phase} line={line} mode={mode} voiceAvailable={!!config?.voice_available} bubbles={bubbles}
            otp={otp} speaking={speaking} muted={muted} status={status} quickLines={quickLines} busy={busy}
            maxChars={config?.max_text_chars ?? 500} startedAt={startedAt}
            onDial={dial} onHangUp={hangUp} onSend={send} onReset={reset} onDismissOtp={() => setOtp(null)}
            onMute={() => { const m = !muted; setMuted(m); voice.current?.setMuted(m); }}
          />
        </div>
        <div className="col col-inside">
          <Inside events={events} scenario={scenario} callActive={inCall} />
        </div>
      </main>
    </div>
  );
}

function AccessGate({ onDone, rejected }: { onDone: () => void; rejected: boolean }) {
  const [code, setCode] = useState("");
  return (
    <main className="gate">
      <h1>Vaani test bench</h1>
      <p>Enter the access code you were given.</p>
      <form onSubmit={(e) => { e.preventDefault(); accessCode.set(code.trim()); onDone(); }}>
        <label className="sr-only" htmlFor="code">Access code</label>
        <input id="code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" autoFocus />
        <button type="submit" disabled={!code.trim()}>Continue</button>
      </form>
      {rejected && <p className="gate-error" role="alert">That code was not accepted. Check it and try again.</p>}
    </main>
  );
}
