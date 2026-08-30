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

export const getVoice = (transactionId: string) =>
  get<{
    status: string;
    outcome: string | null;
    resolution: string;
    language: string;
    is_mock: boolean;
    duration_s: number | null;
    answers: Record<string, { reply: string; response_ms: number; hesitant: boolean }>;
    transcript: string | null;
  }>(`/voice/${transactionId}`);

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
