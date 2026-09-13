/** Talking to the backend. One place, so a failure looks the same everywhere. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type Outcome = "approve" | "intervene" | "decline";

export interface ReasoningStep {
  step: number;
  kind: "context" | "signal" | "assessment";
  observed: string;
  rationale: string;
  score_delta: number;
  running_score: number;
  signal: string | null;
  source: string | null;
  latency_ms: number | null;
}

export interface DecisionRow {
  decision_id: string;
  transaction_id: string;
  outcome: Outcome;
  risk_score: number;
  used_fallback: boolean;
  total_latency_ms: number;
  decided_at: string;
  amount: string;
  currency: string;
  merchant_name: string;
  is_new_beneficiary: boolean;
  signals_pulled: number;
  voice_outcome: string | null;
  analyst_action: AnalystAction | null;
}

export type AnalystAction = "released" | "blocked";

export interface AnalystReview {
  action: AnalystAction;
  reason: string;
  reviewed_at: string;
}

export type Channel = "voice" | "sms" | "app_push";

export interface ChannelVerdict {
  channel: Channel;
  trusted: boolean;
  reason: string;
  blocked_by: string | null;
  /** True when we never pulled the signal that would settle it. Unproven, not barred —
   *  the two are rendered differently and must not be collapsed. */
  evidence_missing: boolean;
}

export interface ChannelAssessment {
  verdicts: ChannelVerdict[];
  preferred: Channel | null;
  strategy: string;
  signals_used: string[];
  /** Every route positively barred by a named signal. Not the same as `preferred` being
   *  null, which also happens when nothing was checked. */
  no_safe_channel: boolean;
}

export interface SignalCall {
  id: string;
  api_name: string;
  source: "live" | "fallback";
  fallback_reason: string | null;
  latency_ms: number;
  request_payload: Record<string, unknown>;
  response_payload: unknown;
  called_at: string;
}

export interface DecisionDetail {
  decision_id: string;
  outcome: Outcome;
  risk_score: number;
  reasoning_trace: ReasoningStep[];
  total_latency_ms: number;
  used_fallback: boolean;
  decided_at: string;
  transaction: {
    id: string;
    amount: string;
    currency: string;
    merchant_name: string;
    beneficiary_id: string;
    is_new_beneficiary: boolean;
    customer_msisdn: string;
    signal_msisdn: string;
    customer_locale: string;
    created_at: string;
    demo_seam: boolean;
  };
  signal_calls: SignalCall[];
  voice_call: {
    id: string;
    language: string;
    status: string;
    outcome: string | null;
    transcript: string | null;
    answers: Record<string, { reply: string; response_ms: number; hesitant: boolean; keypad: string | null }>;
    duration_s: number | null;
    is_mock: boolean;
  } | null;
  channels: ChannelAssessment | null;
  analyst_review: AnalystReview | null;
}

export class ApiError extends Error {}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError("Cannot reach the VerifiedCall API. Is the backend running?");
  }
  if (!response.ok) {
    throw new ApiError(`The API returned ${response.status} for ${path}`);
  }
  return (await response.json()) as T;
}

export const listDecisions = (limit = 40) =>
  get<{ items: DecisionRow[]; total: number }>(`/decisions?limit=${limit}`);

export const getDecision = (id: string) => get<DecisionDetail>(`/decisions/${id}`);

/** Record what a human decided about a payment the agent had already ruled on.
 *
 *  Returns the decision as it now stands. The agent's outcome is unchanged by this —
 *  the review is stored beside it, not over it. */
export async function reviewDecision(
  id: string,
  action: AnalystAction,
  reason: string
): Promise<DecisionDetail> {
  const response = await fetch(`${API_BASE}/decisions/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, reason }),
  });
  if (!response.ok) {
    // 409 is the real one: somebody already reviewed this. The server explains it
    // better than we could, so pass its wording straight through.
    const detail = await response.json().catch(() => null);
    throw new ApiError(
      detail?.detail ?? `The review could not be saved (${response.status}).`
    );
  }
  return (await response.json()) as DecisionDetail;
}

export const getVoice = (transactionId: string) =>
  get<{
    status: string;
    outcome: string | null;
    resolution: string;
    language: string;
    is_mock: boolean;
    duration_s: number | null;
    channel: "phone" | "web";
    answers: Record<string, { reply: string; response_ms: number; hesitant: boolean }>;
    transcript: string | null;
  }>(`/voice/${transactionId}`);

/** The assistant is built on the server, so the browser plays a script it did not write.
 *  The key returned here is the publishable one; the private key never leaves the API. */
export const getWebSession = (transactionId: string) =>
  get<{
    transaction_id: string;
    public_key: string;
    assistant: Record<string, unknown>;
  }>(`/voice/${transactionId}/web-session`);

/** Hand the call id back so the server can resolve it the same way it resolves a phone
 *  call: same polling, same extraction, same hesitation timing. */
export async function reportWebCallStarted(transactionId: string, callId: string) {
  const response = await fetch(`${API_BASE}/voice/${transactionId}/web-started`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId }),
  });
  if (!response.ok) {
    throw new ApiError(`Could not register the call (${response.status})`);
  }
  return response.json() as Promise<{ accepted: boolean; reason?: string }>;
}

export async function evaluatePayment(body: Record<string, unknown>) {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/transactions/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "We could not reach the payment service. Nothing has been charged."
    );
  }
  if (!response.ok) {
    throw new ApiError(
      response.status === 422
        ? "That payment could not be read. Check the phone number format."
        : `The payment service returned ${response.status}. Nothing has been charged.`
    );
  }
  return response.json();
}

export const money = (amount: string | number, currency: string) =>
  `${Number(amount).toLocaleString("en-AE", { minimumFractionDigits: 2 })} ${currency}`;

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour12: false });
