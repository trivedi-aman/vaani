import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, streamEvents, whenSignedOut, type CallHandle } from "./api";
import { Inside } from "./components/Inside";
import { Phone, type Bubble, type Mode, type Phase } from "./components/Phone";
import { ScenarioDrawer } from "./components/ScenarioDrawer";
import { spokenDigits } from "./score";
import type { CallEvent, Line, Scenario, SignedInConfig } from "./types";
import type { VoiceCall } from "./voice";

type View = "scenario" | "phone" | "inside";

const RELOADED_KEY = "vaani-reloaded-for-new-build";

/**
 * The WebRTC client loads only for voice calls. If a new build was deployed
 * while this tab was open, the old file name is gone: reload once to pick up
 * the new build instead of failing the call.
 */
async function loadVoice() {
  try {
    const mod = await import("./voice");
    sessionStorage.removeItem(RELOADED_KEY);
    return mod;
  } catch (e) {
    if (!sessionStorage.getItem(RELOADED_KEY)) {
      sessionStorage.setItem(RELOADED_KEY, "1");
      location.reload();
      return new Promise<never>(() => undefined);      // the page is going away
    }
    throw e;
  }
}

const THEME_KEY = "vaani-theme";
type Theme = "light" | "dark";

function storedTheme(): Theme | null {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : null;
  } catch {
    return null;
  }
}

/** Light, dark, or (until the viewer picks) whatever the system prefers. */
function useTheme(): [Theme, () => void] {
  const system = () => (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const [chosen, setChosen] = useState<Theme | null>(storedTheme);
  const current = chosen ?? system();
  useEffect(() => {
    if (chosen) document.documentElement.dataset.theme = chosen;
    else delete document.documentElement.dataset.theme;
  }, [chosen]);
  const toggle = () => {
    const next: Theme = current === "dark" ? "light" : "dark";
    setChosen(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* private window: the choice lasts for this page only */
    }
  };
  return [current, toggle];
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="theme-toggle" onClick={onToggle} aria-label={`Switch to ${next} theme`}>{next}</button>
  );
}

export function App() {
  const [theme, toggleTheme] = useTheme();
  const [config, setConfig] = useState<SignedInConfig | null>(null);
  const [signedOut, setSignedOut] = useState(false);
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
      if (!cfg.signed_in) {
        setSignedOut(true);
        return;
      }
      setConfig(cfg);
      setScenarios(await api.scenarios());
      setSignedOut(false);
      setLoadError("");
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) {
        setLoadError(e instanceof Error ? e.message : "Could not reach the server.");
      }
    }
  }, []);

  useEffect(() => {
    whenSignedOut(() => {
      setSignedOut(true);
      setConfig(null);
    });
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
      // Load the voice code before starting the call, so a reload for a new build leaves no call open.
      const voiceModule = m === "voice" ? await loadVoice() : null;
      const handle = await api.startCall(l, scenario?.line === l ? scenario.id : undefined);
      call.current = handle;
      closeStream.current = streamEvents(handle, onEvent, () => undefined);
      if (voiceModule) {
        voice.current = await voiceModule.startVoice(handle, config?.ice_servers ?? [], {
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

  const signOut = async () => {
    await hangUp().catch(() => undefined);
    reset();
    await api.logout().catch(() => undefined);
    setConfig(null);
    setSignedOut(true);
  };

  if (signedOut || !config) {
    return signedOut
      ? <SignIn onDone={load} theme={theme} onToggleTheme={toggleTheme} />
      : <div className="loading" aria-busy="true">{loadError || "Loading…"}</div>;
  }

  const bubbles: Bubble[] = events.flatMap((e) => (e.type === "transcript" ? [{ role: e.role, text: e.text }] : []));
  const quickLines = scenario && line === scenario.line
    ? scenario.turns.map((t) => (t === "{otp}" ? (lastOtp ? spokenDigits(lastOtp, scenario.language) : "") : t)).filter(Boolean)
    : [];
  const inCall = phase === "connecting" || phase === "incall";

  const demoDate = new Date(config.demo_today).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const views: [View, string][] = [["scenario", "scenario"], ["phone", "phone"], ["inside", "under the hood"]];

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="shell">
          <a className="wordmark" href="/">Vaani<span className="dot">.</span></a>
          <div className="header-tools">
            <span className="signed-in">{config.user}</span>
            <button className="text-btn" onClick={signOut}>sign out</button>
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
          </div>
        </div>
      </header>

      <main id="main" className="shell" tabIndex={-1}>
        <section className="intro">
          <p className="kicker">voice agent / nbfc support / demo data as of {demoDate}</p>
          <p className="tagline">A voice agent for loan customers and staff that has to get names, dates and numbers right in Indian languages.</p>
        </section>
        {loadError && <p className="banner" role="alert">{loadError} <button className="text-btn" onClick={() => { setLoadError(""); void load(); }}>try again</button></p>}

        <nav className="views primary-nav" aria-label="Sections">
          {views.map(([v, label], i) => (
            <span key={v}>
              {i > 0 && <span className="sep" aria-hidden="true">·</span>}
              <button aria-current={view === v ? "page" : undefined} onClick={() => setView(v)}>{label}</button>
            </span>
          ))}
        </nav>

        <div className="bench" data-view={view}>
          <div className="col col-scenario">
            <ScenarioDrawer scenarios={scenarios} selected={scenario} onSelect={setScenario} disabled={inCall} />
          </div>
          <div className="col col-phone">
            <Phone
              phase={phase} line={line} mode={mode} voiceAvailable={config.voice_available} bubbles={bubbles}
              otp={otp} speaking={speaking} muted={muted} status={status} quickLines={quickLines} busy={busy}
              maxChars={config.max_text_chars} startedAt={startedAt}
              onDial={dial} onHangUp={hangUp} onSend={send} onReset={reset} onDismissOtp={() => setOtp(null)}
              onMute={() => { const m = !muted; setMuted(m); voice.current?.setMuted(m); }}
            />
          </div>
          <div className="col col-inside">
            <Inside events={events} scenario={scenario} callActive={inCall} />
          </div>
        </div>
      </main>

      <footer className="site-footer">
        <div className="shell">
          <span>Vaani. All names, loans and numbers are invented; nothing here dials a real phone.</span>
          <span className="foot-links"><a href="https://www.amantrivedi.com">amantrivedi.com</a></span>
        </div>
      </footer>
    </>
  );
}

function SignIn({ onDone, theme, onToggleTheme }: { onDone: () => void; theme: Theme; onToggleTheme: () => void }) {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(userId.trim(), password);
      setPassword("");
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="signin-tools"><ThemeToggle theme={theme} onToggle={onToggleTheme} /></div>
      <main className="signin" id="main">
        <p className="root-mark">Vaani<span className="dot">.</span></p>
        <p className="root-note">a voice agent for Indian lending / by invitation</p>
        <form className="signin-form" onSubmit={submit}>
          <label htmlFor="user-id">user id</label>
          <input id="user-id" value={userId} onChange={(e) => setUserId(e.target.value)} autoComplete="username"
                 autoCapitalize="none" spellCheck={false} autoFocus required maxLength={40} />
          <label htmlFor="password">password</label>
          <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" required maxLength={200} />
          <button type="submit" className="button-link" disabled={busy || !userId.trim() || !password}>
            {busy ? "signing in…" : "sign in"}
          </button>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
        <p className="signin-note">Access is by invitation. If you were sent here without an account, ask Aman for one.</p>
      </main>
    </>
  );
}
