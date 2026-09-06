"use client";

/**
 * The customer's side, as a mobile banking app.
 *
 * It was a form with a scenario dropdown, which demonstrated the backend but did not
 * look like anything a person uses. The payment now happens where a real one does: an
 * account screen, a transfer, a confirmation, and then the security call.
 *
 * The demo scenarios still exist because the four network profiles are the point, but
 * they sit in a panel that reads as a demo control rather than pretending to be part of
 * the product.
 *
 * Reliability matters more than polish. Every failure has a written state and nothing
 * hangs: if the backend is unreachable the customer is told plainly that nothing has
 * been charged.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { IncomingCall } from "@/components/IncomingCall";
import { useDeviceLocation } from "@/components/useDeviceLocation";
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
    label: "Routine payment, known payee",
    payee: "Carrefour Mall of the Emirates",
    amount: "240.00",
    newPayee: false,
    signal: "+99999991001",
    hour: 14,
    note: "Everything is normal. The agent should not spend time on network checks.",
  },
  {
    id: "elsewhere",
    label: "Large transfer, phone is elsewhere",
    payee: "Direct transfer",
    amount: "18500.00",
    newPayee: true,
    signal: "+99999991000",
    hour: 23,
    note: "Reads as somebody else operating the account, so calling would not reach the customer.",
  },
  {
    id: "coerced",
    label: "Large transfer, phone is right here",
    payee: "Direct transfer to a 'safe account'",
    amount: "42000.00",
    newPayee: true,
    signal: "+99999991004",
    hour: 23,
    note: "The headline case. The customer really is doing this, so we call them.",
  },
  {
    id: "partial",
    label: "Moderate transfer, partial location match",
    payee: "Al Ansari Exchange",
    amount: "6300.00",
    newPayee: true,
    signal: "+99999991003",
    hour: 23,
    note: "Not enough to decline, too much to wave through.",
  },
  {
    id: "outage",
    label: "Network outage on every check",
    payee: "Direct transfer",
    amount: "9000.00",
    newPayee: true,
    signal: "+99999990500",
    hour: 23,
    note: "Proves the system degrades to cached data and says so, rather than falling over.",
  },
] as const;

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ar", label: "العربية" },
  { code: "hi", label: "हिन्दी" },
  { code: "ur", label: "اردو" },
];

const RECENT = [
  { name: "Salary — Emirates Holdings", when: "Today", amount: "+18,400.00" },
  { name: "DEWA", when: "Yesterday", amount: "-612.35" },
  { name: "Talabat", when: "2 Sep", amount: "-88.00" },
  { name: "Emaar — rent", when: "1 Sep", amount: "-7,500.00" },
];

const BALANCE = 96420.55;

type Phase = "idle" | "deciding" | "calling" | "done" | "error";

interface Decision {
  transaction_id: string;
  outcome: Outcome;
  risk_score: number;
  summary: string;
  signals_pulled: string[];
  latency_ms: number;
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

export default function BankApp() {
  const [scenarioId, setScenarioId] = useState<string>(SCENARIOS[2].id);
  const [language, setLanguage] = useState("en");
  const [phase, setPhase] = useState<Phase>("idle");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDemo, setShowDemo] = useState(false);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  const location = useDeviceLocation();
  const scenario = SCENARIOS.find((s) => s.id === scenarioId) ?? SCENARIOS[0];

  const stopPolling = useCallback(() => {
    if (polling.current) {
      clearInterval(polling.current);
      polling.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  // The payment waits for an answer about location, not for permission to be granted.
  // Refusing is a valid answer that the backend scores; being asked and not having
  // replied yet is not.
  const locationAnswered =
    location.stage === "granted" ||
    location.stage === "denied" ||
    location.stage === "unavailable";

  const busy = phase === "deciding" || phase === "calling";
  const canPay = locationAnswered && !busy;

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
        merchant_name: scenario.payee,
        beneficiary_id: `BEN-${scenario.id.toUpperCase()}`,
        is_new_beneficiary: scenario.newPayee,
        customer_msisdn: "+971500000000",
        signal_msisdn: scenario.signal,
        customer_locale: language,
        local_hour: scenario.hour,
        device_latitude: location.latitude,
        device_longitude: location.longitude,
        device_location_accuracy_m: location.accuracy,
        device_location_denied: location.stage !== "granted",
      })) as Decision;

      setDecision(result);

      if (result.outcome !== "intervene") {
        setPhase("done");
        return;
      }

      // Held for a call. The watcher has to outlast the conversation, which is capped
      // at two minutes, plus the transcription and extraction that happen after it.
      setPhase("calling");
      let attempts = 0;
      const giveUpAfter = 300;
      polling.current = setInterval(async () => {
        attempts += 1;
        try {
          const v = (await getVoice(result.transaction_id)) as VoiceState;
          setVoice(v);
          if (v.status === "completed" || v.status === "failed" || attempts > giveUpAfter) {
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

  const callIsUp =
    decision?.outcome === "intervene" &&
    voice?.channel === "web" &&
    voice.status !== "completed" &&
    voice.status !== "failed";

  return (
    <main className="app">
      <div className="phone">
        <header className="app-bar">
          <div>
            <p className="app-bank">VerifiedCall Bank</p>
            <p className="app-greet">Good evening, Rizwanul</p>
          </div>
          <span className="app-avatar">RA</span>
        </header>

        <section className="acct">
          <p className="acct-label">Current account</p>
          <p className="acct-number">AE07 0331 •••• •••• 4429</p>
          <p className="acct-balance">{money(BALANCE, "AED")}</p>
        </section>

        <LocationBadge location={location} />

        {phase !== "done" && phase !== "error" && (
          <section className="pay-card">
            <h2>Send money</h2>

            <div className="pay-row">
              <span>To</span>
              <strong>{scenario.payee}</strong>
            </div>
            <div className="pay-row">
              <span>Amount</span>
              <strong className="pay-amount">{money(scenario.amount, "AED")}</strong>
            </div>
            <div className="pay-row">
              <span>They speak</span>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                disabled={busy}
                aria-label="Customer language"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>

            <button className="pay" onClick={pay} disabled={!canPay}>
              {phase === "deciding" ? (
                <>
                  <span className="spinner" /> Checking this payment…
                </>
              ) : phase === "calling" ? (
                <>
                  <span className="spinner" /> Security check in progress…
                </>
              ) : !locationAnswered ? (
                "Confirm your location to continue"
              ) : (
                `Send ${money(scenario.amount, "AED")}`
              )}
            </button>

            {!locationAnswered && (
              <p className="hint">
                We check where your phone is before releasing a transfer. You can
                decline; we will note that we could not check and decide anyway.
              </p>
            )}
          </section>
        )}

        {phase === "error" && (
          <section className="result" data-o="error">
            <p className="eyebrow" style={{ color: "var(--stop)" }}>
              Payment not completed
            </p>
            <h2>We could not check this payment</h2>
            <p>{error}</p>
            <button className="pay" onClick={() => setPhase("idle")}>
              Back
            </button>
          </section>
        )}

        {decision && phase !== "error" && (
          <CustomerResult
            decision={decision}
            voice={voice}
            calling={phase === "calling"}
            onDone={() => {
              setPhase("idle");
              setDecision(null);
              setVoice(null);
            }}
          />
        )}

        <section className="recent">
          <h3>Recent activity</h3>
          {RECENT.map((r) => (
            <div key={r.name} className="recent-row">
              <div>
                <p className="recent-name">{r.name}</p>
                <p className="recent-when">{r.when}</p>
              </div>
              <p className={r.amount.startsWith("+") ? "recent-in" : "recent-out"}>
                {r.amount}
              </p>
            </div>
          ))}
        </section>

        <section className="demo">
          <button className="demo-toggle" onClick={() => setShowDemo((v) => !v)}>
            {showDemo ? "Hide" : "Show"} demo controls
          </button>
          {showDemo && (
            <div className="demo-body">
              <p className="hint">
                Each scenario uses a different sandbox number, so the network returns a
                different signal profile. Numbers and behaviour are in
                docs/camara-findings.md.
              </p>
              {SCENARIOS.map((s) => (
                <label key={s.id} className="demo-choice">
                  <input
                    type="radio"
                    name="scenario"
                    checked={s.id === scenarioId}
                    onChange={() => setScenarioId(s.id)}
                    disabled={busy}
                  />
                  <span>
                    <strong>{s.label}</strong>
                    <em>{s.note}</em>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>
      </div>

      {callIsUp && (
        <IncomingCall
          transactionId={decision.transaction_id}
          amountLabel={money(scenario.amount, "AED")}
          beneficiary={scenario.payee}
        />
      )}
    </main>
  );
}

function LocationBadge({ location }: { location: ReturnType<typeof useDeviceLocation> }) {
  if (location.stage === "granted") {
    const accuracy =
      location.accuracy != null ? ` · accurate to ${Math.round(location.accuracy)}m` : "";
    return (
      <div className="loc is-on">
        <PinIcon />
        <span>
          Location confirmed{accuracy}. We will check this against the mobile network.
        </span>
      </div>
    );
  }

  if (location.stage === "denied" || location.stage === "unavailable") {
    return (
      <div className="loc is-off">
        <PinIcon />
        <span>
          {location.error} We will note that this check is missing and decide without it.
        </span>
        <button onClick={location.request}>Retry</button>
      </div>
    );
  }

  return (
    <div className="loc">
      <PinIcon />
      <span>
        {location.stage === "asking"
          ? "Finding your phone…"
          : "Confirm where your phone is before you transfer."}
      </span>
      {location.stage !== "asking" && (
        <button onClick={location.request}>Allow</button>
      )}
    </div>
  );
}

function PinIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="10" r="2.4" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function CustomerResult({
  decision,
  voice,
  calling,
  onDone,
}: {
  decision: Decision;
  voice: VoiceState | null;
  calling: boolean;
  onDone: () => void;
}) {
  if (decision.outcome === "approve") {
    return (
      <section className="result" data-o="approve">
        <p className="eyebrow">Sent</p>
        <h2>Your transfer is on its way</h2>
        <p>Checked in {(decision.latency_ms / 1000).toFixed(1)} seconds.</p>
        <button className="pay" onClick={onDone}>
          Done
        </button>
      </section>
    );
  }

  if (decision.outcome === "decline") {
    return (
      <section className="result" data-o="decline">
        <p className="eyebrow" style={{ color: "var(--stop)" }}>
          Stopped
        </p>
        <h2>We have not sent this payment</h2>
        <p>
          Something about this transfer did not look right, and we could not reach you
          on the number registered to this account. Nothing has left your balance.
        </p>
        <button className="pay" onClick={onDone}>
          Done
        </button>
      </section>
    );
  }

  return (
    <section className="result" data-o="intervene">
      <p className="eyebrow" style={{ color: "var(--hold)" }}>
        {calling ? "Security check" : "On hold"}
      </p>
      <h2>{calling ? "We need a word before this goes" : headline(voice)}</h2>
      <p>{calling ? "Answer the call to continue." : body(voice)}</p>

      {voice && Object.keys(voice.answers ?? {}).length > 0 && (
        <div className="answers">
          {Object.entries(voice.answers).map(([key, answer]) => (
            <div key={key} className="answer-row">
              <span>{QUESTION_LABEL[key] ?? key}</span>
              <strong>
                {answer.reply}
                {answer.hesitant && <em> · hesitated</em>}
              </strong>
            </div>
          ))}
        </div>
      )}

      {!calling && (
        <button className="pay" onClick={onDone}>
          Done
        </button>
      )}
    </section>
  );
}

function headline(voice: VoiceState | null): string {
  if (!voice) return "We could not reach you";
  if (voice.outcome === "confirmed_legitimate") return "Thank you. Your transfer is going through";
  if (voice.outcome === "scam_detected") return "We have stopped this payment";
  if (voice.outcome === "no_answer") return "We could not reach you";
  return "We are having someone look at this";
}

function body(voice: VoiceState | null): string {
  if (!voice) {
    return "Your payment is on hold until we can speak to you. Nothing has been charged.";
  }
  switch (voice.outcome) {
    case "confirmed_legitimate":
      return "Everything you told us checked out.";
    case "scam_detected":
      return "From what you told us, someone else was directing this payment. Your money has stayed where it is.";
    case "no_answer":
      return "We could not reach you, so the payment is held rather than sent.";
    default:
      return "Your answers were not clear enough for us to release this automatically, so a person from our fraud team will review it. Nothing has been charged.";
  }
}
