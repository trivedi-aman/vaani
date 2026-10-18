import type { CallEvent, Scenario } from "./types";

export interface Check {
  label: string;
  status: "pass" | "fail" | "manual";
  detail: string;
}

const ENTITY_FIELDS: Record<string, string[]> = {
  customer_id: ["name"],
  dob: ["dob"],
  phone: ["phone"],
  loan_id: ["loan_id"],
  ticket_id: ["ticket_id"],
  district: ["district"],
  pincode: ["pincode"],
  amount: ["amount"],
  date: ["date"],
};

const PLAIN: Record<string, string> = {
  customer_id: "Caller identified as",
  dob: "Date of birth",
  phone: "Mobile number",
  loan_id: "Loan ID",
  ticket_id: "Ticket ID",
  district: "City or district",
  pincode: "Pincode",
  amount: "Amount",
  date: "Date",
  financial_year: "Financial year",
  month: "Month",
};

/** Compare what happened on a call with what the scenario expects. */
export function scoreCall(scenario: Scenario, events: CallEvent[]): Check[] {
  const checks: Check[] = [];
  const entities = events.filter((e) => e.type === "entity");
  for (const [kind, expected] of Object.entries(scenario.expected.entities)) {
    const fields = ENTITY_FIELDS[kind];
    const label = `${PLAIN[kind] ?? kind}: ${expected.replace("|", ", ")}`;
    if (!fields) {
      checks.push({ label, status: "manual", detail: "Check the conversation." });
      continue;
    }
    const seen = entities.filter((e) => fields.includes(e.field));
    const hit = seen.find((e) => e.value === expected);
    checks.push(
      hit
        ? { label, status: "pass", detail: `Heard "${hit.heard}", ${hit.confidence} confidence.` }
        : {
            label,
            status: "fail",
            detail: seen.length ? `Understood as ${seen.map((e) => (e.value ?? "nothing").replace("|", ", ")).join("; ")}.` : "Never captured.",
          },
    );
  }
  const called = new Set(events.flatMap((e) => (e.type === "tool" && e.outcome === "ok" ? [e.name] : [])));
  for (const tool of scenario.expected.tools) {
    checks.push({
      label: `Used ${tool.replaceAll("_", " ")}`,
      status: called.has(tool) ? "pass" : "fail",
      detail: called.has(tool) ? "Called successfully." : "Not called, or refused.",
    });
  }
  const said = events
    .flatMap((e) => (e.type === "transcript" && e.role === "bot" ? [e.text.toLowerCase()] : []))
    .join(" ");
  for (const phrase of scenario.expected.must_not ?? []) {
    const leaked = said.includes(phrase.toLowerCase());
    checks.push({
      label: `Never says "${phrase}"`,
      status: leaked ? "fail" : "pass",
      detail: leaked ? "The bot said it." : "Not said.",
    });
  }
  checks.push({ label: "Expected outcome", status: "manual", detail: scenario.expected.outcome });
  return checks;
}

const DIGITS: Record<string, string[]> = {
  hi: ["shunya", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau"],
  mr: ["shunya", "ek", "don", "teen", "chaar", "paach", "saha", "saat", "aath", "nau"],
  ta: ["poojyam", "onnu", "rendu", "moonu", "naalu", "anju", "aaru", "ezhu", "ettu", "onbadhu"],
  en: ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
};

/** Say an OTP the way a caller in this language would. */
export function spokenDigits(code: string, language: string): string {
  const words = DIGITS[language] ?? DIGITS.en;
  return [...code].map((d) => words[Number(d)]).join(" ");
}
