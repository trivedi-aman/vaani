export type Line = "customer" | "staff";

/** Before sign-in the server says only `signed_in: false`. */
export type Config =
  | { signed_in: false }
  | {
      signed_in: true;
      user: string;
      voice_available: boolean;
      demo_today: string;
      max_call_seconds: number;
      max_text_chars: number;
      ice_servers: RTCIceServer[];
    };
export type SignedInConfig = Extract<Config, { signed_in: true }>;

export interface Persona {
  customer_id?: string;
  name: string;
  name_native?: string;
  dob?: string;
  phone?: string;
  loan_id?: string;
  city?: string;
  state?: string;
  pincode?: string;
  employee_id?: string;
  role?: string;
  pin?: string;
}

export interface Scenario {
  id: string;
  line: Line;
  title: string;
  language: string;
  difficulty: "easy" | "medium" | "hard";
  persona: Persona;
  goal: string;
  hard_variant?: string;
  turns: string[];
  expected: {
    entities: Record<string, string>;
    tools: string[];
    outcome: string;
    must_not?: string[];
  };
}

export interface Candidate {
  value: string;
  label: string;
  distance: number;
}

/** Events the server streams for one call. */
export type CallEvent = { ts: number } & (
  | { type: "call"; status: string; reason?: string; mode?: string; line?: string }
  | { type: "transcript"; role: "user" | "bot"; text: string; language?: string | null }
  | { type: "heard"; text: string; language?: string | null }
  | {
      type: "entity";
      field: string;
      kind: string;
      heard: string;
      value: string | null;
      confidence: "high" | "medium" | "low";
      normalised: string;
      candidates: Candidate[];
      issues: string[];
      action: "accept" | "read_back" | "ask_again";
      checked?: string;
    }
  | { type: "tool"; name: string; args: Record<string, unknown>; outcome: string; result: unknown; ms: number }
  | { type: "node"; name: string; ms?: number; tools?: string[]; tool_calls?: string[] }
  | { type: "otp"; code: string; to: string }
  | { type: "state"; verified: boolean; locked: boolean; role?: string }
  | { type: "latency"; agent_ms?: number; ttfb_ms?: Record<string, number> }
  | { type: "error"; message: string }
  | { type: "guard"; blocked: string }
);

export type EntityEvent = Extract<CallEvent, { type: "entity" }>;
export type ToolEvent = Extract<CallEvent, { type: "tool" }>;
