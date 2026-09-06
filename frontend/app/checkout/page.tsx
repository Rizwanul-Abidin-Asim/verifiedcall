"use client";

/**
 * The customer's side: a mobile banking app at the moment of sending money.
 *
 * Home, then send, then a review sheet, then one deliberate slide to confirm. If the
 * network signals say something is wrong, the screen becomes the security call. The
 * demo scenarios still exist because the four network profiles are the point, but they
 * live in a drawer that admits to being a demo control.
 *
 * Reliability matters more than polish. Every failure has a written state and nothing
 * hangs: if the backend is unreachable the customer is told plainly that nothing has
 * been charged.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { AmountPad, formatAmount } from "@/components/bank/AmountPad";
import { SlideToSend } from "@/components/bank/SlideToSend";
import { IncomingCall } from "@/components/IncomingCall";
import { useDeviceLocation } from "@/components/useDeviceLocation";
import { ApiError, evaluatePayment, getVoice, type Outcome } from "../../lib/api";

/** Signal numbers come from the measured sandbox matrix in docs/camara-findings.md. */
const PROFILES = [
  {
    id: "clean",
    label: "All clear",
    signal: "+99999991001",
    note: "Every network check comes back clean.",
  },
  {
    id: "elsewhere",
    label: "Phone is somewhere else",
    signal: "+99999991000",
    note: "SIM swapped, calls forwarded, and the phone is not where this payment is.",
  },
  {
    id: "coerced",
    label: "Phone is right here",
    signal: "+99999991004",
    note: "Same bad signals, but the phone is exactly where the payment claims. The headline case.",
  },
  {
    id: "partial",
    label: "Partial location match",
    signal: "+99999991003",
    note: "Not enough to decline, too much to wave through.",
  },
  {
    id: "outage",
    label: "Network outage",
    signal: "+99999990500",
    note: "Every network call fails. Proves the fallback and says so.",
  },
] as const;

const PAYEES = [
  { id: "ahmed", name: "Ahmed Karim", iban: "AE45 0260 0010 1234 5678 901", initials: "AK", saved: true },
  { id: "mum", name: "Mum", iban: "AE22 0330 0000 0012 3456 789", initials: "M", saved: true },
  { id: "dewa", name: "DEWA", iban: "AE07 0331 2345 6789 0123 456", initials: "D", saved: true },
] as const;

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ar", label: "العربية" },
  { code: "hi", label: "हिन्दी" },
  { code: "ur", label: "اردو" },
];

const RECENT = [
  { name: "Salary · Emirates Holdings", when: "Today", amount: "+18,400.00", in: true },
  { name: "DEWA", when: "Yesterday", amount: "−612.35", in: false },
  { name: "Talabat", when: "2 Sep", amount: "−88.00", in: false },
  { name: "Emaar · rent", when: "1 Sep", amount: "−7,500.00", in: false },
];

const BALANCE = 96420.55;

type Screen = "home" | "send" | "review" | "result" | "cards" | "request";
type Phase = "idle" | "deciding" | "calling" | "done" | "error";

interface Decision {
  transaction_id: string;
  outcome: Outcome;
  risk_score: number;
  latency_ms: number;
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
  others_present: "Is anyone with you?",
  asked_to_pay: "Did someone ask you to pay?",
  told_to_keep_secret: "Told not to tell your bank?",
};

export default function BankApp() {
  const [screen, setScreen] = useState<Screen>("home");
  // Nothing on the home screen is decorative. Request adds a pending row to the
  // activity list, and the card can be frozen, so every button does what it says.
  const [recent, setRecent] = useState(RECENT);
  const [frozen, setFrozen] = useState(false);
  const [reqPayee, setReqPayee] = useState<string>("ahmed");
  const [reqAmount, setReqAmount] = useState("");
  const [payeeId, setPayeeId] = useState<string>("ahmed");
  const [newName, setNewName] = useState("");
  const [newIban, setNewIban] = useState("");
  const [amount, setAmount] = useState("");
  const [language, setLanguage] = useState("en");
  const [profileId, setProfileId] = useState<string>("coerced");
  const [drawer, setDrawer] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  const location = useDeviceLocation();
  const profile = PROFILES.find((p) => p.id === profileId) ?? PROFILES[2];
  const isNewPayee = payeeId === "new";
  const payee = isNewPayee
    ? { name: newName.trim() || "New payee", iban: newIban.trim(), initials: "+" }
    : PAYEES.find((p) => p.id === payeeId) ?? PAYEES[0];

  const amountNumber = Number(amount || "0");
  const amountOk = amountNumber > 0 && amountNumber <= BALANCE;
  const payeeOk = !isNewPayee || (newName.trim().length > 1 && newIban.replace(/\s/g, "").length >= 15);

  const locationAnswered =
    location.stage === "granted" || location.stage === "denied" || location.stage === "unavailable";

  const stopPolling = useCallback(() => {
    if (polling.current) {
      clearInterval(polling.current);
      polling.current = null;
    }
  }, []);
  useEffect(() => stopPolling, [stopPolling]);

  // The demo drawer can stage the headline case in one tap, but everything it fills in
  // stays editable. A judge who types their own amount gets a real decision on it.
  const stageHeadline = () => {
    setPayeeId("new");
    setNewName("Safe account");
    setNewIban("AE90 0999 0000 0000 0000 001");
    setAmount("42000");
    setProfileId("coerced");
    setDrawer(false);
    setScreen("send");
  };

  const reset = () => {
    stopPolling();
    setPhase("idle");
    setDecision(null);
    setVoice(null);
    setError(null);
    setScreen("home");
    setAmount("");
  };

  const send = useCallback(async () => {
    stopPolling();
    setPhase("deciding");
    setDecision(null);
    setVoice(null);
    setError(null);

    try {
      const result = (await evaluatePayment({
        amount: amountNumber.toFixed(2),
        currency: "AED",
        merchant_name: payee.name,
        beneficiary_id: isNewPayee ? `NEW-${payee.iban.replace(/\s/g, "")}` : `SAVED-${payeeId}`,
        is_new_beneficiary: isNewPayee,
        customer_msisdn: "+971500000000",
        signal_msisdn: profile.signal,
        customer_locale: language,
        local_hour: new Date().getHours(),
        device_latitude: location.latitude,
        device_longitude: location.longitude,
        device_location_accuracy_m: location.accuracy,
        device_location_denied: location.stage !== "granted",
      })) as Decision;

      setDecision(result);

      if (result.outcome !== "intervene") {
        setPhase("done");
        setScreen("result");
        return;
      }

      setPhase("calling");
      let attempts = 0;
      polling.current = setInterval(async () => {
        attempts += 1;
        try {
          const v = (await getVoice(result.transaction_id)) as VoiceState;
          setVoice(v);
          if (v.status === "completed" || v.status === "failed" || attempts > 300) {
            stopPolling();
            setPhase("done");
            setScreen("result");
          }
        } catch {
          if (attempts > 300) {
            stopPolling();
            setPhase("done");
            setScreen("result");
          }
        }
      }, 1000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not reach the bank. Nothing has been sent.");
      setPhase("error");
    }
  }, [amountNumber, payee, isNewPayee, payeeId, profile.signal, language, location, stopPolling]);

  const callIsUp =
    decision?.outcome === "intervene" &&
    voice?.channel === "web" &&
    voice.status !== "completed" &&
    voice.status !== "failed";

  return (
    <main className="bk">
      <div className="bk-phone" data-screen={screen}>
        {/* ------------------------------------------------------------ home */}
        <section className="bk-screen bk-home" aria-hidden={screen !== "home"}>
          <header className="bk-bar">
            <div>
              <p className="bk-eyebrow">VerifiedCall Bank</p>
              <h1 className="bk-greet">Good evening, Rizwanul</h1>
            </div>
            <span className="bk-avatar">RA</span>
          </header>

          <div className="bk-card">
            <span className="bk-card-sheen" aria-hidden="true" />
            <p className="bk-card-label">Current account</p>
            <p className="bk-card-iban">AE07 0331 •••• •••• 4429</p>
            <p className="bk-card-balance">
              <span className="bk-card-ccy">AED</span>
              {formatAmount(BALANCE.toFixed(2))}
            </p>
          </div>

          <div className="bk-actions">
            <button className="bk-action is-primary" onClick={() => setScreen("send")}>
              <ArrowIcon />
              <span>Send</span>
            </button>
            <button className="bk-action" onClick={() => setScreen("request")}>
              <RequestIcon />
              <span>Request</span>
            </button>
            <button className="bk-action" onClick={() => setScreen("cards")}>
              <CardIcon />
              <span>Cards</span>
            </button>
          </div>

          <div className="bk-list">
            <h2 className="bk-h2">Recent</h2>
            {recent.map((r, i) => (
              <div key={`${r.name}-${i}`} className="bk-row">
                <span className="bk-row-dot" data-in={r.in} />
                <div className="bk-row-main">
                  <p className="bk-row-name">{r.name}</p>
                  <p className="bk-row-when">{r.when}</p>
                </div>
                <p className={`bk-row-amt${r.in ? " is-in" : ""}`}>{r.amount}</p>
              </div>
            ))}
          </div>

          <div className="bk-drawer">
            <button className="bk-drawer-toggle" onClick={() => setDrawer((v) => !v)}>
              {drawer ? "Hide demo controls" : "Demo controls"}
            </button>
            {drawer && (
              <div className="bk-drawer-body">
                <button className="bk-stage" onClick={stageHeadline}>
                  Stage the headline case
                  <small>42,000 AED to a new "safe account", phone right here</small>
                </button>
                <p className="bk-drawer-label">Network profile for the next payment</p>
                {PROFILES.map((p) => (
                  <label key={p.id} className="bk-choice">
                    <input
                      type="radio"
                      name="profile"
                      checked={p.id === profileId}
                      onChange={() => setProfileId(p.id)}
                    />
                    <span>
                      <strong>{p.label}</strong>
                      <em>{p.note}</em>
                    </span>
                  </label>
                ))}
                <a className="bk-drawer-link" href="/dashboard">
                  Open the fraud-ops console →
                </a>
              </div>
            )}
          </div>
        </section>

        {/* ------------------------------------------------------------ send */}
        <section className="bk-screen bk-send" aria-hidden={screen !== "send"}>
          <header className="bk-bar">
            <button className="bk-back" onClick={() => setScreen("home")} aria-label="Back">
              <BackIcon />
            </button>
            <h1 className="bk-title">Send money</h1>
            <span className="bk-bar-spacer" />
          </header>

          <div className="bk-payees" role="radiogroup" aria-label="Payee">
            {PAYEES.map((p) => (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={payeeId === p.id}
                className={`bk-payee${payeeId === p.id ? " is-on" : ""}`}
                onClick={() => setPayeeId(p.id)}
              >
                <span className="bk-payee-avatar">{p.initials}</span>
                <span className="bk-payee-name">{p.name}</span>
              </button>
            ))}
            <button
              type="button"
              role="radio"
              aria-checked={isNewPayee}
              className={`bk-payee is-new${isNewPayee ? " is-on" : ""}`}
              onClick={() => setPayeeId("new")}
            >
              <span className="bk-payee-avatar">+</span>
              <span className="bk-payee-name">New</span>
            </button>
          </div>

          {isNewPayee && (
            <div className="bk-fields">
              <label className="bk-field">
                <span>Name</span>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Who are you paying?"
                  autoComplete="off"
                />
              </label>
              <label className="bk-field">
                <span>IBAN</span>
                <input
                  value={newIban}
                  onChange={(e) => setNewIban(e.target.value.toUpperCase())}
                  placeholder="AE00 0000 0000 0000 0000 000"
                  autoComplete="off"
                  inputMode="text"
                  className="bk-mono"
                />
              </label>
              <p className="bk-hint">A first payment to someone new is what we look at hardest.</p>
            </div>
          )}

          <AmountPad value={amount} onChange={setAmount} />

          <button
            className="bk-cta"
            disabled={!amountOk || !payeeOk}
            onClick={() => setScreen("review")}
          >
            {amountNumber > BALANCE ? "That's more than you have" : "Review"}
          </button>
        </section>

        {/* --------------------------------------------------------- request */}
        <section className="bk-screen bk-request" aria-hidden={screen !== "request"}>
          <header className="bk-bar">
            <button className="bk-back" onClick={() => setScreen("home")} aria-label="Back">
              <BackIcon />
            </button>
            <h1 className="bk-title">Request money</h1>
            <span className="bk-bar-spacer" />
          </header>

          <div className="bk-payees" role="radiogroup" aria-label="Request from">
            {PAYEES.map((p) => (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={reqPayee === p.id}
                className={`bk-payee${reqPayee === p.id ? " is-on" : ""}`}
                onClick={() => setReqPayee(p.id)}
              >
                <span className="bk-payee-avatar">{p.initials}</span>
                <span className="bk-payee-name">{p.name}</span>
              </button>
            ))}
          </div>

          <AmountPad value={reqAmount} onChange={setReqAmount} />

          <button
            className="bk-cta"
            disabled={Number(reqAmount || "0") <= 0}
            onClick={() => {
              const from = PAYEES.find((p) => p.id === reqPayee) ?? PAYEES[0];
              setRecent((prev) => [
                {
                  name: `Request · ${from.name}`,
                  when: "Pending",
                  amount: `+${formatAmount(Number(reqAmount).toFixed(2))}`,
                  in: true,
                },
                ...prev,
              ]);
              setReqAmount("");
              setScreen("home");
            }}
          >
            Send request
          </button>
        </section>

        {/* ----------------------------------------------------------- cards */}
        <section className="bk-screen bk-cards" aria-hidden={screen !== "cards"}>
          <header className="bk-bar">
            <button className="bk-back" onClick={() => setScreen("home")} aria-label="Back">
              <BackIcon />
            </button>
            <h1 className="bk-title">Cards</h1>
            <span className="bk-bar-spacer" />
          </header>

          <div className={`bk-card bk-cardface${frozen ? " is-frozen" : ""}`}>
            <span className="bk-card-sheen" aria-hidden="true" />
            <p className="bk-card-label">{frozen ? "Frozen" : "Debit · Visa"}</p>
            <p className="bk-cardface-pan">•••• •••• •••• 4429</p>
            <div className="bk-cardface-foot">
              <span>RIZWANUL ASIM</span>
              <span>09/29</span>
            </div>
          </div>

          <button className="bk-cta is-ghost" onClick={() => setFrozen((v) => !v)}>
            {frozen ? "Unfreeze card" : "Freeze card"}
          </button>
          <p className="bk-hint">
            {frozen
              ? "Payments on this card are paused until you unfreeze it."
              : "Freezing stops every payment on this card instantly. Unfreeze any time."}
          </p>

          <div className="bk-list">
            <h2 className="bk-h2">Controls</h2>
            <div className="bk-row">
              <div className="bk-row-main">
                <p className="bk-row-name">Online payments</p>
              </div>
              <p className="bk-row-amt is-in">On</p>
            </div>
            <div className="bk-row">
              <div className="bk-row-main">
                <p className="bk-row-name">Contactless</p>
              </div>
              <p className="bk-row-amt is-in">On</p>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------- result */}
        <section className="bk-screen bk-result" aria-hidden={screen !== "result"}>
          {decision && (
            <Outcome
              decision={decision}
              voice={voice}
              amount={amountNumber}
              payee={payee.name}
              onDone={reset}
            />
          )}
        </section>
      </div>

      {/* ---------------------------------------------------------- review */}
      {screen === "review" && (
        <div className="bk-sheet-backdrop" onClick={() => phase === "idle" && setScreen("send")}>
          <div className="bk-sheet" onClick={(e) => e.stopPropagation()}>
            <span className="bk-sheet-handle" aria-hidden="true" />
            <h2 className="bk-h2">Review</h2>

            <div className="bk-review">
              <div className="bk-review-row">
                <span>To</span>
                <strong>{payee.name}</strong>
              </div>
              <div className="bk-review-row">
                <span>IBAN</span>
                <strong className="bk-mono">{payee.iban || "—"}</strong>
              </div>
              <div className="bk-review-row is-amount">
                <span>Amount</span>
                <strong>
                  <small>AED</small> {formatAmount(amountNumber.toFixed(2))}
                </strong>
              </div>
              <div className="bk-review-row">
                <span>They speak</span>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  disabled={phase !== "idle"}
                  aria-label="Language for the security call"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>{l.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <LocationLine location={location} />

            {phase === "error" && <p className="bk-error">{error}</p>}

            <SlideToSend
              label={`Slide to send ${formatAmount(amountNumber.toFixed(2))} AED`}
              disabled={!locationAnswered}
              busy={phase === "deciding" || phase === "calling"}
              onSend={send}
            />
            {!locationAnswered && (
              <p className="bk-hint">Answer the location prompt above to unlock sending.</p>
            )}
            {phase === "calling" && (
              <p className="bk-hint">Security check in progress. Answer the call to continue.</p>
            )}
          </div>
        </div>
      )}

      {callIsUp && decision && (
        <IncomingCall
          transactionId={decision.transaction_id}
          amountLabel={`${formatAmount(amountNumber.toFixed(2))} AED`}
          beneficiary={payee.name}
        />
      )}
    </main>
  );
}

/* ------------------------------------------------------------------ pieces */

function LocationLine({ location }: { location: ReturnType<typeof useDeviceLocation> }) {
  if (location.stage === "granted") {
    return (
      <div className="bk-loc is-on">
        <PinIcon />
        <span>Location confirmed. We check this against the mobile network before sending.</span>
      </div>
    );
  }
  if (location.stage === "denied" || location.stage === "unavailable") {
    return (
      <div className="bk-loc is-off">
        <PinIcon />
        <span>{location.error} We'll note the check is missing and decide without it.</span>
        <button type="button" onClick={location.request}>Retry</button>
      </div>
    );
  }
  return (
    <div className="bk-loc">
      <PinIcon />
      <span>{location.stage === "asking" ? "Finding your phone…" : "Confirm where your phone is."}</span>
      {location.stage !== "asking" && (
        <button type="button" onClick={location.request}>Allow</button>
      )}
    </div>
  );
}

function Outcome({
  decision,
  voice,
  amount,
  payee,
  onDone,
}: {
  decision: Decision;
  voice: VoiceState | null;
  amount: number;
  payee: string;
  onDone: () => void;
}) {
  const sent =
    decision.outcome === "approve" || voice?.outcome === "confirmed_legitimate";
  const stopped = decision.outcome === "decline" || voice?.outcome === "scam_detected";
  const tone = sent ? "sent" : stopped ? "stopped" : "held";

  const title = sent
    ? "Sent"
    : stopped
      ? "We've stopped this payment"
      : voice?.outcome === "no_answer"
        ? "We couldn't reach you"
        : "We're having someone look at this";

  const body = sent
    ? `${formatAmount(amount.toFixed(2))} AED is on its way to ${payee}.`
    : decision.outcome === "decline"
      ? "This transfer didn't look right and we couldn't reach you on the number registered to this account. Nothing has left your balance."
      : voice?.outcome === "scam_detected"
        ? "From what you told us, someone else was directing this payment. Your money has stayed where it is."
        : voice?.outcome === "no_answer"
          ? "Your payment is held rather than sent. Nothing has been charged."
          : "Your answers weren't clear enough to release this automatically, so a person from our fraud team will review it. Nothing has been charged.";

  return (
    <div className="bk-outcome" data-tone={tone}>
      <span className="bk-outcome-icon" aria-hidden="true">
        {sent ? <TickIcon /> : stopped ? <StopIcon /> : <HoldIcon />}
      </span>
      <h1 className="bk-outcome-title">{title}</h1>
      <p className="bk-outcome-body">{body}</p>

      {voice && Object.keys(voice.answers ?? {}).length > 0 && (
        <div className="bk-answers">
          {Object.entries(voice.answers).map(([key, a]) => (
            <div key={key} className="bk-answer">
              <span>{QUESTION_LABEL[key] ?? key}</span>
              <strong>
                {a.reply}
                {a.hesitant && <em>hesitated</em>}
              </strong>
            </div>
          ))}
        </div>
      )}

      <button className="bk-cta" onClick={onDone}>Done</button>
    </div>
  );
}

/* ------------------------------------------------------------------- icons */

const stroke = { stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

function ArrowIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12h14m0 0-6-6m6 6-6 6" {...stroke} /></svg>;
}
function BackIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 12H5m0 0 6-6m-6 6 6 6" {...stroke} /></svg>;
}
function RequestIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14m0 0-6-6m6 6 6-6" {...stroke} /></svg>;
}
function CardIcon() {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2" {...stroke} /><path d="M3 10h18" {...stroke} /></svg>;
}
function PinIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z" {...stroke} /><circle cx="12" cy="10" r="2.4" {...stroke} /></svg>;
}
function TickIcon() {
  return <svg width="36" height="36" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path className="bk-draw" d="m5 12.5 4.5 4.5L19 7" {...stroke} strokeWidth="2.6" /></svg>;
}
function StopIcon() {
  return <svg width="36" height="36" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path className="bk-draw" d="M6 6l12 12M18 6 6 18" {...stroke} strokeWidth="2.6" /></svg>;
}
function HoldIcon() {
  return <svg width="36" height="36" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" {...stroke} strokeWidth="2.2" className="bk-draw" /><path d="M12 7v5l3 2" {...stroke} strokeWidth="2.2" /></svg>;
}
