"use client";

/**
 * What the customer sees while the payment is held and the checks run.
 *
 * The wait is real — several seconds of live calls to the mobile operator and an agent
 * deciding which of them are worth making — and it used to be a slider that said
 * "Sending…" and nothing else. Silence during a wait reads as a hang, and on a demo it
 * reads as a broken build.
 *
 * The labels below are not a fake progress bar. Each one names something that genuinely
 * happens in that order, and none of them advances ahead of the clock. If the work takes
 * longer than expected the last line simply stays on screen; nothing here claims to be
 * finished before it is.
 *
 * There was an elapsed-seconds readout here. It was the real number, but a counter next
 * to steps that advance on a timer reads as a progress bar someone invented, and looking
 * invented is as bad as being invented on a screen whose whole job is to be believed.
 */

import { useEffect, useState } from "react";

// Each line has to be true for EVERY payment, including the ordinary ones.
//
// These used to read "Asking the mobile network about this line" and "Working out how we
// can reach you". On a routine payment the agent decides no network check is worth the
// customer's time and pulls nothing at all — so both lines described work that never
// happened, on exactly the payments most customers make.
//
// The third line now says what is actually true, and it happens to say the most
// interesting thing about this system: most payments do not need asking about.
const STEPS = [
  { at: 0, text: "Holding the payment" },
  { at: 1.2, text: "Deciding which checks this payment needs" },
  { at: 4, text: "Asking the network, if it needs asking" },
] as const;

export default function CheckingNetwork() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 200);
    return () => clearInterval(id);
  }, []);

  // The furthest step whose time has passed. Never runs ahead of the clock.
  const reached = STEPS.reduce((best, s, i) => (elapsed >= s.at ? i : best), 0);

  return (
    <div className="bk-checking" role="status" aria-live="polite">
      <div className="bk-checking-head">
        <span className="bk-checking-spinner" aria-hidden="true" />
        <span className="bk-checking-title">Checking before we send</span>
      </div>

      <ol className="bk-checking-steps">
        {STEPS.map((step, i) => (
          <li key={step.text} data-state={i < reached ? "done" : i === reached ? "now" : "next"}>
            <span className="bk-checking-dot" aria-hidden="true" />
            {step.text}
          </li>
        ))}
      </ol>

      <p className="bk-checking-note">
        Any checks we run are live requests to the mobile operator, which is why this
        takes a moment. Nothing has left your account.
      </p>
    </div>
  );
}
