import { useEffect, useRef, useState } from "react";
import type { Line } from "../types";

export type Phase = "idle" | "connecting" | "incall" | "ended";
export type Mode = "voice" | "text";

export interface Bubble {
  role: "user" | "bot";
  text: string;
}

interface Props {
  phase: Phase;
  line: Line | null;
  mode: Mode;
  voiceAvailable: boolean;
  bubbles: Bubble[];
  otp: { code: string; to: string } | null;
  speaking: "user" | "bot" | null;
  muted: boolean;
  status: string;
  quickLines: string[];
  busy: boolean;
  maxChars: number;
  startedAt: number | null;
  onDial: (line: Line, mode: Mode) => void;
  onHangUp: () => void;
  onSend: (text: string) => void;
  onMute: () => void;
  onDismissOtp: () => void;
  onReset: () => void;
}

const CONTACTS: { line: Line; name: string; note: string }[] = [
  { line: "customer", name: "Vaani Customer Care", note: "Loans, EMIs, documents, complaints" },
  { line: "staff", name: "Vaani Staff Helpdesk", note: "Case lookups for employees" },
];

export function Phone(props: Props) {
  return (
    <div className="device" aria-label="Simulated phone">
      <div className="screen">
        <StatusBar />
        {props.otp && (
          <button className="sms" onClick={props.onDismissOtp} aria-live="assertive">
            <strong>VAANI-LN</strong>
            <span>Your one-time password is {props.otp.code}. Never share it with anyone who calls you. Sent to {props.otp.to}.</span>
          </button>
        )}
        {props.phase === "idle" ? <Dialer {...props} /> : <InCall {...props} />}
      </div>
    </div>
  );
}

function StatusBar() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="statusbar" aria-hidden="true">
      <span>{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
      <span>demo network</span>
    </div>
  );
}

function Dialer({ voiceAvailable, onDial }: Props) {
  const [mode, setMode] = useState<"voice" | "text">(voiceAvailable ? "voice" : "text");
  return (
    <div className="dialer">
      <h2>contacts</h2>
      <ul className="contacts">
        {CONTACTS.map((c) => (
          <li key={c.line}>
            <div>
              <span className="contact-name">{c.name}</span>
              <span className="contact-note">{c.note}</span>
            </div>
            <button className="dial" onClick={() => onDial(c.line, mode)} aria-label={`Call ${c.name}`}>
              call
            </button>
          </li>
        ))}
      </ul>
      <fieldset className="mode">
        <legend>talk by</legend>
        <label>
          <input type="radio" name="mode" checked={mode === "voice"} disabled={!voiceAvailable} onChange={() => setMode("voice")} />
          voice
        </label>
        <label>
          <input type="radio" name="mode" checked={mode === "text"} onChange={() => setMode("text")} />
          typing
        </label>
      </fieldset>
      {!voiceAvailable && <p className="hint">Voice is switched off on this server, so calls use typing.</p>}
      <p className="hint">Nothing here dials a real number.</p>
    </div>
  );
}

function InCall(props: Props) {
  const { phase, line, mode, bubbles, speaking, muted, status, startedAt } = props;
  const name = CONTACTS.find((c) => c.line === line)?.name ?? "";
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [bubbles.length]);

  return (
    <div className="incall">
      <header className="incall-head">
        <span className="callee">{name}</span>
        <span className="call-status">{phase === "ended" ? "Call ended" : phase === "connecting" ? "Connecting…" : <Timer since={startedAt} />}</span>
        {mode === "voice" && phase === "incall" && (
          <span className={`speaking ${speaking ?? ""}`}>{speaking === "bot" ? "Vaani is speaking" : speaking === "user" ? "Listening" : " "}</span>
        )}
      </header>
      <div className="bubbles" ref={log} aria-live="polite">
        {bubbles.map((b, i) => (
          <p key={i} className={`bubble ${b.role}`}>{b.text}</p>
        ))}
      </div>
      {status && <p className="phone-status" role="status">{status}</p>}
      {phase === "ended" ? (
        <div className="call-actions">
          <button className="secondary" onClick={props.onReset}>back to contacts</button>
        </div>
      ) : mode === "text" ? (
        <Composer {...props} />
      ) : (
        <div className="call-actions">
          <button className="secondary" onClick={props.onMute} aria-pressed={muted}>{muted ? "unmute" : "mute"}</button>
          <button className="hangup" onClick={props.onHangUp}>end call</button>
        </div>
      )}
    </div>
  );
}

function Composer({ onSend, onHangUp, busy, quickLines, maxChars, phase }: Props) {
  const [text, setText] = useState("");
  const send = () => {
    const t = text.trim();
    if (t && !busy) {
      onSend(t);
      setText("");
    }
  };
  return (
    <div className="composer">
      {quickLines.length > 0 && (
        <div className="quick" aria-label="Lines from the scenario">
          {quickLines.map((q, i) => (
            <button key={i} className="chip" onClick={() => setText(q)} title="Put this line in the box">{q}</button>
          ))}
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); send(); }}>
        <label className="sr-only" htmlFor="say">What you say</label>
        <input id="say" value={text} maxLength={maxChars} onChange={(e) => setText(e.target.value)}
               placeholder={busy ? "Vaani is answering…" : "Type what you would say"} disabled={phase !== "incall"} autoComplete="off" />
        <button type="submit" disabled={busy || !text.trim()}>say</button>
      </form>
      <button className="hangup small" onClick={onHangUp}>end call</button>
    </div>
  );
}

function Timer({ since }: { since: number | null }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  if (!since) return <>00:00</>;
  const s = Math.floor((Date.now() - since) / 1000);
  return <>{String(Math.floor(s / 60)).padStart(2, "0")}:{String(s % 60).padStart(2, "0")}</>;
}
