"use client";

/**
 * The demo surface. A pretend merchant checkout that fires the same webhook a real
 * payment gateway would, then shows the customer's side of what happens next.
 *
 * Reliability matters more than polish here, so every failure has a written state and
 * nothing ever hangs: if the backend is unreachable the customer is told plainly that
 * nothing has been charged.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { IncomingCall } from "@/components/IncomingCall";
import {
  ApiError,
  evaluatePayment,
  getVoice,
  money,
  type Outcome,
} from "../../lib/api";

/** Signal numbers come from the measured sandbox matrix in docs/camara-findings.md. */
const SCENARIOS = [
  {
    id: "clean",
    label: "1. Routine payment to a known payee",
    amount: "240.00",
    merchant: "Carrefour Mall of the Emirates",
    newPayee: false,
    signal: "+99999991001",
    hour: 14,
    note: "Everything is normal. The agent should not spend time on network checks.",
  },
  {
    id: "elsewhere",
    label: "2. Large transfer, phone is not where the payment is",
    amount: "18500.00",
    merchant: "Direct transfer",
    newPayee: true,
    signal: "+99999991000",
    hour: 23,
    note: "Reads as somebody else operating the account, so calling would not reach the customer.",
  },
  {
    id: "coerced",
    label: "3. Large transfer, phone is exactly where expected",
    amount: "42000.00",
    merchant: "Direct transfer to a 'safe account'",
    newPayee: true,
    signal: "+99999991004",
    hour: 23,
    note: "The headline case. The customer really is doing this, so we phone them.",
  },
  {
    id: "partial",
    label: "4. Moderate transfer, partial location match",
    amount: "6300.00",
    merchant: "Al Ansari Exchange",
    newPayee: true,
    signal: "+99999991003",
    hour: 23,
    note: "Not enough to decline, too much to wave through.",
  },
  {
    id: "outage",
    label: "5. Network outage (forces every CAMARA call to fail)",
    amount: "9000.00",
    merchant: "Direct transfer",
    newPayee: true,
    signal: "+99999990500",
    hour: 23,
    note: "Proves the system degrades to cached data and says so, rather than falling over.",
  },
] as const;

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ar", label: "Arabic" },
  { code: "hi", label: "Hindi" },
  { code: "ur", label: "Urdu" },
];

/** Mirrors the simulator in app/voice/vapi_client.py, which keys off the last digit. */
const MOCK_CUSTOMERS = [
  { number: "+971500000000", label: "…000  admits they were told to pay" },
  { number: "+971500000001", label: "…001  answers cleanly" },
  { number: "…002", label: "…002  denies it, but hesitates" },
  { number: "+971500000009", label: "…009  does not pick up" },
];

type Phase = "idle" | "deciding" | "calling" | "done" | "error";

interface Decision {
  transaction_id: string;
  outcome: Outcome;
  risk_score: number;
  summary: string;
  signals_pulled: string[];
  latency_ms: number;
  used_fallback: boolean;
  agent_mode: string;
}

interface VoiceState {
  status: string;
  outcome: string | null;
  resolution: string;
  language: string;
  channel?: "phone" | "web";
  answers: Record<string, { reply: string; response_ms: number; hesitant: boolean }>;
}

const QUESTION_LABEL: Record<string, string> = {
  others_present: "Is anyone with you right now?",
  asked_to_pay: "Did someone ask you to make this payment?",
  told_to_keep_secret: "Were you told not to tell your bank?",
};

export default function Checkout() {
  const [scenarioId, setScenarioId] = useState<string>(SCENARIOS[2].id);
  const [phone, setPhone] = useState("+971500000000");
  const [language, setLanguage] = useState("en");
  const [phase, setPhase] = useState<Phase>("idle");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  const scenario = SCENARIOS.find((s) => s.id === scenarioId) ?? SCENARIOS[0];

  const stopPolling = useCallback(() => {
    if (polling.current) {
      clearInterval(polling.current);
      polling.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  async function pay() {
    stopPolling();
    setPhase("deciding");
    setDecision(null);
    setVoice(null);
    setError(null);

    try {
      const result = (await evaluatePayment({
        amount: scenario.amount,
        currency: "AED",
        merchant_name: scenario.merchant,
        beneficiary_id: `BEN-${scenario.id.toUpperCase()}`,
        is_new_beneficiary: scenario.newPayee,
        customer_msisdn: phone.trim(),
        signal_msisdn: scenario.signal,
        customer_locale: language,
        local_hour: scenario.hour,
      })) as Decision;

      setDecision(result);

      if (result.outcome !== "intervene") {
        setPhase("done");
        return;
      }

      // Held for a call. Watch it until it resolves, and give up rather than hang.
      //
      // The ceiling used to be forty seconds, which was shorter than a real
      // conversation. A call that ran sixty-six seconds finished correctly on the
      // server and the customer never saw the result: polling had already stopped, so
      // the screen sat on "checking what you told us" forever. The call itself is
      // capped at two minutes, and the provider still has to transcribe and extract
      // afterwards, so the watcher has to outlast all of that.
      setPhase("calling");
      let attempts = 0;
      const giveUpAfter = 300; // five minutes at one second apart
      polling.current = setInterval(async () => {
        attempts += 1;
        try {
          const v = await getVoice(result.transaction_id);
          setVoice(v as VoiceState);
          if (v.status === "completed" || v.status === "failed") {
            stopPolling();
            setPhase("done");
          } else if (attempts > giveUpAfter) {
            // Stop watching, but say so rather than implying an answer. The payment is
            // held either way, which is the safe state.
            stopPolling();
            setPhase("done");
          }
        } catch {
          if (attempts > giveUpAfter) {
            stopPolling();
            setPhase("done");
          }
        }
      }, 1000);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Nothing has been charged."
      );
      setPhase("error");
    }
  }

  const busy = phase === "deciding" || phase === "calling";

  return (
    <main>
      <div className="checkout-wrap">
        <p className="eyebrow">Merchant checkout</p>
        <h1>Confirm your payment</h1>
        <p className="sub">
          A stand-in for a bank app or an online checkout. Submitting sends the same
          webhook a real payment gateway would, and the money stays held until
          VerifiedCall answers.
        </p>

        <div className="card card-pad">
          <div className="field">
            <label htmlFor="scenario">Scenario</label>
            <select
              id="scenario"
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              disabled={busy}
            >
              {SCENARIOS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            <p className="hint">{scenario.note}</p>
          </div>

          <div className="field">
            <label htmlFor="phone">Phone number we would call</label>
            <input
              id="phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              disabled={busy}
              placeholder="+971500000000"
            />
            <p className="hint">
              Simulated calls are scripted by the last digit, the same way the CAMARA
              sandbox works:{" "}
              {MOCK_CUSTOMERS.map((m) => m.label).join(" · ")}
            </p>
          </div>

          <div className="field">
            <label htmlFor="lang">Customer language</label>
            <select
              id="lang"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={busy}
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>

          <button className="pay" onClick={pay} disabled={busy}>
            {phase === "deciding" ? (
              <>
                <span className="spinner" /> Checking this payment…
              </>
            ) : phase === "calling" ? (
              <>
                <span className="spinner" />{" "}
                {voice?.channel === "web" ? "Waiting for you…" : "Calling you now…"}
              </>
            ) : (
              `Pay ${money(scenario.amount, "AED")}`
            )}
          </button>
        </div>

        {phase === "error" && (
          <div className="result" data-o="error">
            <p className="eyebrow" style={{ color: "var(--stop)" }}>
              Payment not completed
            </p>
            <h2>We could not check this payment</h2>
            <p>{error}</p>
          </div>
        )}

        {/* A held payment on the in-app channel takes over the screen, because that
            is what a call does. Everything after the call starts is shared with the
            phone path. */}
        {decision?.outcome === "intervene" &&
          voice?.channel === "web" &&
          voice.status !== "completed" &&
          voice.status !== "failed" && (
            <IncomingCall
              transactionId={decision.transaction_id}
              amountLabel={money(scenario.amount, "AED")}
              beneficiary={scenario.merchant}
            />
          )}

        {decision && phase !== "error" && (
          <CustomerResult
            decision={decision}
            voice={voice}
            calling={phase === "calling"}
          />
        )}
      </div>
    </main>
  );
}

function CustomerResult({
  decision,
  voice,
  calling,
}: {
  decision: Decision;
  voice: VoiceState | null;
  calling: boolean;
}) {
  if (decision.outcome === "approve") {
    return (
      <div className="result" data-o="approve">
        <p className="eyebrow" style={{ color: "var(--ok)" }}>
          Payment approved
        </p>
        <h2>Your payment has gone through</h2>
        <p>
          Checked in {Math.round(decision.latency_ms)}ms
          {decision.signals_pulled.length === 0
            ? ", without needing any network checks."
            : `, using ${decision.signals_pulled.length} network check(s).`}
        </p>
      </div>
    );
  }

  if (decision.outcome === "decline") {
    return (
      <div className="result" data-o="decline">
        <p className="eyebrow" style={{ color: "var(--stop)" }}>
          Payment stopped
        </p>
        <h2>We have blocked this payment</h2>
        <p>
          Your money has not left your account. The device on this account does not
          appear to be where the payment came from, so we stopped it. Your bank will
          be in touch.
        </p>
      </div>
    );
  }

  return (
    <div className="result" data-o="intervene">
      <p className="eyebrow" style={{ color: "var(--hold)" }}>
        Payment on hold
      </p>
      <h2>
        {calling ? (
          <>
            <span className="spinner" /> We are calling you to confirm this payment
          </>
        ) : (
          resolutionHeadline(voice)
        )}
      </h2>
      <p>
        {calling
          ? "Please answer the call. Your money has not moved and will not move until we have spoken to you."
          : resolutionBody(voice)}
      </p>

      {voice && Object.keys(voice.answers ?? {}).length > 0 && (
        <div className="qa">
          {Object.entries(voice.answers).map(([key, answer]) => (
            <div className="qa-row" key={key}>
              <span className="q">{QUESTION_LABEL[key] ?? key}</span>
              <span className="a">
                {answer.reply}
                {answer.hesitant ? " (hesitated)" : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function resolutionHeadline(voice: VoiceState | null): string {
  if (!voice) return "We could not reach you";
  if (voice.outcome === "confirmed_legitimate") return "Thank you. Your payment is going through";
  if (voice.outcome === "scam_detected") return "We have stopped this payment";
  if (voice.outcome === "no_answer") return "We could not reach you";
  return "We are checking this with a colleague";
}

function resolutionBody(voice: VoiceState | null): string {
  if (!voice) {
    return "Your payment is still on hold and someone from your bank will contact you.";
  }
  switch (voice.outcome) {
    case "confirmed_legitimate":
      return "You confirmed you were not asked to make this payment, so we have released it.";
    case "scam_detected":
      return "From your answers it looks like somebody asked you to send this money. Your money is safe and has not left your account. Please do not continue any call you are currently on.";
    case "no_answer":
      return "Your payment is on hold until we can speak to you. Nothing has left your account.";
    default:
      return "Your answers were not clear enough for us to release this automatically, so a member of the fraud team will call you back. Your money has not moved.";
  }
}
