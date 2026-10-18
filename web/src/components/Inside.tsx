import { useState } from "react";
import type { CallEvent, EntityEvent, Scenario, ToolEvent } from "../types";
import { scoreCall } from "../score";

const FIELD_NAMES: Record<string, string> = {
  name: "Name", dob: "Date of birth", phone: "Mobile number", loan_id: "Loan ID", ticket_id: "Ticket ID",
  district: "City or district", pincode: "Pincode", amount: "Amount", date: "Date", otp: "OTP",
  employee_id: "Employee ID", pin: "PIN", financial_year: "Financial year",
};
/** Values as a person reads them: "Barmer|Rajasthan" -> "Barmer, Rajasthan", a customer id -> "Customer C0004". */
export function readable(field: string, value: string | null): string {
  if (value === null) return "not understood";
  if (field === "name" && /^C\d{4}$/.test(value)) return `Customer ${value}`;
  return value.replace("|", ", ");
}

const ACTIONS: Record<EntityEvent["action"], string> = {
  accept: "Accepted", read_back: "Read back to confirm", ask_again: "Asked again",
};

type Tab = "understood" | "conversation" | "steps" | "check";

interface Props {
  events: CallEvent[];
  scenario: Scenario | null;
  callActive: boolean;
}

export function Inside({ events, scenario, callActive }: Props) {
  const [tab, setTab] = useState<Tab>("understood");
  const entities = events.filter((e): e is EntityEvent => e.type === "entity");
  const tabs: [Tab, string][] = [
    ["understood", `Understood${entities.length ? ` (${entities.length})` : ""}`],
    ["conversation", "Conversation"],
    ["steps", "Agent steps"],
    ["check", "Check"],
  ];
  return (
    <section className="inside" aria-label="What the agent is doing">
      <div className="tabs" role="tablist">
        {tabs.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      <div className="tab-body">
        {tab === "understood" && <Understood entities={entities} callActive={callActive} />}
        {tab === "conversation" && <Conversation events={events} />}
        {tab === "steps" && <Steps events={events} />}
        {tab === "check" && <CheckCall events={events} scenario={scenario} />}
      </div>
    </section>
  );
}

function Understood({ entities, callActive }: { entities: EntityEvent[]; callActive: boolean }) {
  if (!entities.length) {
    return (
      <p className="empty">
        {callActive
          ? "When the caller gives a name, date, number or place, you will see how it was heard, what it became, what it matched, and how sure the agent is."
          : "Start a call. Every value the caller speaks shows up here as it is understood."}
      </p>
    );
  }
  return (
    <ol className="tracks">
      {[...entities].reverse().map((e, i) => (
        <li key={`${e.ts}-${i}`} className={`track ${e.confidence}`}>
          <h3>{FIELD_NAMES[e.field] ?? e.field}</h3>
          <div className="steps-row">
            <div className="step">
              <span className="step-label">Heard</span>
              <span className="step-value heard">{e.heard}</span>
            </div>
            {e.normalised && e.normalised !== e.value && e.normalised.toLowerCase() !== e.heard.toLowerCase() && (
              <div className="step">
                <span className="step-label">Normalised</span>
                <span className="step-value">{e.normalised}</span>
              </div>
            )}
            <div className="step">
              <span className="step-label">Became</span>
              <span className="step-value strong">{readable(e.field, e.value)}</span>
            </div>
            <div className="step verdict">
              <span className="step-label">{e.confidence[0].toUpperCase() + e.confidence.slice(1)} confidence</span>
              <span className="step-value">{ACTIONS[e.action]}</span>
            </div>
          </div>
          {e.candidates.length > 1 && (
            <ul className="candidates" aria-label="Closest matches">
              {e.candidates.map((c) => (
                <li key={c.value}>
                  <span>{c.label}</span>
                  <span className="distance" title="Sound distance: lower is closer">{c.distance.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
          {e.issues.length > 0 && <p className="issues">{e.issues.join(". ")}.</p>}
        </li>
      ))}
    </ol>
  );
}

function Conversation({ events }: { events: CallEvent[] }) {
  const lines = events.filter((e) => e.type === "transcript" || e.type === "heard");
  if (!lines.length) return <p className="empty">Nothing said yet.</p>;
  return (
    <ul className="convo">
      {lines.map((e, i) =>
        e.type === "transcript" ? (
          <li key={i} className={e.role}>
            <span className="who">{e.role === "bot" ? "Vaani" : "Caller"}</span>
            <span>{e.text}</span>
          </li>
        ) : e.type === "heard" ? (
          <li key={i} className="heard-line">
            <span className="who">Speech-to-text{e.language ? `, ${e.language}` : ""}</span>
            <span>{e.text}</span>
          </li>
        ) : null,
      )}
    </ul>
  );
}

function Steps({ events }: { events: CallEvent[] }) {
  const steps = events.filter((e) => ["tool", "node", "latency", "error", "guard", "state"].includes(e.type));
  if (!steps.length) return <p className="empty">The agent has not done anything yet.</p>;
  return (
    <ol className="trace">
      {steps.map((e, i) => (
        <li key={i} className={`trace-${e.type}`}>{describe(e)}</li>
      ))}
    </ol>
  );
}

function describe(e: CallEvent) {
  switch (e.type) {
    case "tool":
      return <ToolStep e={e} />;
    case "node":
      if (e.name === "gate") return <span className="quiet">{e.tools?.length ?? 0} tools available to this caller</span>;
      return <span className="quiet">Nova answered in {e.ms} ms{e.tool_calls?.length ? `, asked for ${e.tool_calls.join(", ")}` : ""}</span>;
    case "latency":
      if (e.agent_ms) return <span className="quiet">Turn took {e.agent_ms} ms in the agent</span>;
      return <span className="quiet">Speech latency: {Object.entries(e.ttfb_ms ?? {}).map(([k, v]) => `${k.split("#")[0]} ${v} ms`).join(", ")}</span>;
    case "error":
      return <span className="bad">{e.message}</span>;
    case "guard":
      return <span className="bad">Reply blocked: {e.blocked}</span>;
    case "state":
      return <span>{e.locked ? "Verification locked after repeated failures" : e.verified ? `Caller verified${e.role ? ` (${e.role})` : ""}` : "Not verified"}</span>;
    default:
      return null;
  }
}

function ToolStep({ e }: { e: ToolEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className="tool-line" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="tool-name">{e.name.replaceAll("_", " ")}</span>
        <span className={`outcome ${e.outcome}`}>{e.outcome === "ok" ? "done" : e.outcome}</span>
        <span className="quiet">{e.ms} ms</span>
      </button>
      {open && <pre className="json">{JSON.stringify({ asked_with: e.args, returned: e.result }, null, 2)}</pre>}
    </div>
  );
}

function CheckCall({ events, scenario }: { events: CallEvent[]; scenario: Scenario | null }) {
  if (!scenario) return <p className="empty">Pick a scenario before the call to check it against what should happen.</p>;
  const checks = scoreCall(scenario, events);
  const passed = checks.filter((c) => c.status === "pass").length;
  const auto = checks.filter((c) => c.status !== "manual").length;
  return (
    <div>
      <p className="score">{passed} of {auto} automatic checks passed for “{scenario.title}”.</p>
      <ul className="checks">
        {checks.map((c, i) => (
          <li key={i} className={c.status}>
            <span className="mark" aria-hidden="true">{c.status === "pass" ? "✓" : c.status === "fail" ? "✕" : "?"}</span>
            <div>
              <span className="check-label">{c.label}</span>
              <span className="check-detail">{c.detail}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
