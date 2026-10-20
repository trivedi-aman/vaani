import { useMemo, useState } from "react";
import type { Line, Scenario } from "../types";

const LANGUAGE_NAMES: Record<string, string> = {
  hi: "Hindi", en: "English", mr: "Marathi", ta: "Tamil", bn: "Bengali", te: "Telugu",
};

interface Props {
  scenarios: Scenario[];
  selected: Scenario | null;
  onSelect: (s: Scenario | null) => void;
  disabled: boolean;
}

export function ScenarioDrawer({ scenarios, selected, onSelect, disabled }: Props) {
  const [line, setLine] = useState<Line>("customer");
  const [language, setLanguage] = useState("all");
  const languages = useMemo(() => [...new Set(scenarios.map((s) => s.language))], [scenarios]);
  const shown = scenarios.filter((s) => s.line === line && (language === "all" || s.language === language));

  if (selected) return <Persona scenario={selected} onBack={() => onSelect(null)} disabled={disabled} />;

  return (
    <section className="drawer" aria-label="Scenarios">
      <header className="drawer-head">
        <h2>Pick a scenario</h2>
        <p>Each one gives you a made-up identity and a problem to call about.</p>
      </header>
      <div className="segmented" role="tablist" aria-label="Line">
        {(["customer", "staff"] as Line[]).map((l) => (
          <button key={l} role="tab" aria-selected={line === l} onClick={() => setLine(l)}>
            {l === "customer" ? "customer care" : "staff helpdesk"}
          </button>
        ))}
      </div>
      <label className="field-inline">
        language
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="all">all</option>
          {languages.map((l) => (
            <option key={l} value={l}>{LANGUAGE_NAMES[l] ?? l}</option>
          ))}
        </select>
      </label>
      <ul className="scenario-list">
        {shown.map((s) => (
          <li key={s.id}>
            <button className="scenario" onClick={() => onSelect(s)} disabled={disabled}>
              <span className="scenario-title">{s.title}</span>
              <span className="scenario-meta">
                {LANGUAGE_NAMES[s.language] ?? s.language}
                {s.difficulty === "hard" && <span className="hard">hard</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Persona({ scenario, onBack, disabled }: { scenario: Scenario; onBack: () => void; disabled: boolean }) {
  const p = scenario.persona;
  const rows: [string, string | undefined][] = scenario.line === "customer"
    ? [["Name", p.name], ["In script", p.name_native], ["Date of birth", p.dob], ["Mobile", p.phone],
       ["Loan ID", p.loan_id], ["City", p.city && `${p.city}, ${p.state}`], ["Pincode", p.pincode]]
    : [["Name", p.name], ["Employee ID", p.employee_id], ["PIN", p.pin], ["Role", p.role]];
  return (
    <section className="drawer" aria-label="Your identity">
      <button className="link" onClick={onBack} disabled={disabled}>← all scenarios</button>
      <h2>{scenario.title}</h2>
      <p className="goal">{scenario.goal}</p>
      <dl className="id-card">
        {rows.filter(([, v]) => v).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd lang={k === "In script" ? scenario.language : undefined}>{v}</dd>
          </div>
        ))}
      </dl>
      {scenario.hard_variant && (
        <div className="twist">
          <h3>The tricky part</h3>
          <p>{scenario.hard_variant}</p>
        </div>
      )}
      <div className="opening">
        <h3>You could start with</h3>
        <p>“{scenario.turns.find((t) => !/^employee id|^\{otp\}/.test(t)) ?? scenario.turns[0]}”</p>
      </div>
      <p className="fineprint">All data here is invented. Dial {scenario.line === "customer" ? "Customer care" : "Staff helpdesk"} on the phone.</p>
    </section>
  );
}
