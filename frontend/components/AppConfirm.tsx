"use client";

/**
 * The in-app confirmation, used when the network says the voice line is not ours.
 *
 * This is deliberately not a "confirm / cancel" dialog, and the reason is the whole
 * point of the product. A coerced customer taps confirm exactly as fast as a free one
 * does — if somebody is standing over them telling them to press the green button, they
 * press the green button. A yes/no prompt cannot tell the two apart and pretending
 * otherwise would be worse than useless.
 *
 * What this channel can do, which the phone call cannot, is arrive silently. The scam
 * depends on controlling what the customer knows for the next few minutes: the caller
 * talks over anything that contradicts them, and a bank calling to warn her is a call he
 * can answer. A notification is not. So the job here is not to extract a confession —
 * it is to put the sentence the fraudster has been talking over in front of her eyes,
 * on a screen only she can see.
 *
 * The question we do ask is chosen so the honest answer is safe to give while being
 * watched. "Is someone helping you with this?" is answerable with a tap that looks
 * innocuous to anyone glancing over, where "Are you being scammed?" is not.
 */

import { useState } from "react";

interface Props {
  amount: string;
  currency: string;
  payee: string;
  /** Why the call was not used. Shown so the customer is not left wondering. */
  reason: string;
  onAnswer: (coerced: boolean) => void;
}

export default function AppConfirm({ amount, currency, payee, reason, onAnswer }: Props) {
  const [sent, setSent] = useState<boolean | null>(null);

  function answer(coerced: boolean) {
    setSent(coerced);
    // A beat before the screen changes, so the tap registers as an action taken rather
    // than the interface jumping out from under a frightened person's thumb.
    setTimeout(() => onAnswer(coerced), 700);
  }

  return (
    <div className="bk-sheet-backdrop">
      <div className="bk-sheet bk-confirm" role="dialog" aria-modal="true"
           aria-labelledby="bk-confirm-title">
        <span className="bk-sheet-handle" aria-hidden="true" />

        <div className="bk-confirm-head">
          <span className="bk-confirm-chip">Payment held</span>
          <h2 id="bk-confirm-title" className="bk-confirm-title">
            Before this money leaves
          </h2>
          <p className="bk-confirm-amount">
            {Number(amount).toLocaleString("en-AE", { minimumFractionDigits: 2 })}{" "}
            {currency} <span>to {payee}</span>
          </p>
        </div>

        {/* The sentence the caller has been talking over. */}
        <div className="bk-confirm-warn">
          <p>
            Your bank will never ask you to move money to a “safe account”. Neither will
            the police, the courts, or any government department.
          </p>
          <p>If someone on a call told you to make this transfer, it is a scam.</p>
        </div>

        {sent === null ? (
          <>
            <p className="bk-confirm-ask">Is anyone helping you with this transfer?</p>
            <div className="bk-confirm-actions">
              <button type="button" className="bk-confirm-btn" data-tone="stop"
                      onClick={() => answer(true)}>
                Yes, someone is guiding me
              </button>
              <button type="button" className="bk-confirm-btn" data-tone="go"
                      onClick={() => answer(false)}>
                No, this is my own decision
              </button>
            </div>
            <p className="bk-confirm-why">{reason}</p>
          </>
        ) : (
          <p className="bk-confirm-ask" aria-live="polite">
            {sent
              ? "Thank you. This payment is stopped and nothing has left your account."
              : "Thank you. We are releasing the payment now."}
          </p>
        )}
      </div>
    </div>
  );
}
