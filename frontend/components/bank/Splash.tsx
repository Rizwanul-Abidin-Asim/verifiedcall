"use client";

/**
 * The landing moment: five seconds of the app's own name before the home screen.
 *
 * It does one job — say who this is — and then gets out of the way. The bar along the
 * bottom is the real five-second clock, not decoration, so nobody wonders whether the
 * screen has frozen; and a tap anywhere ends it early for a presenter who has seen it
 * before. Nothing here touches the app's state beyond telling the page it is finished.
 */

import { useEffect, useState } from "react";

export const SPLASH_MS = 5000;

export default function Splash({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const leave = setTimeout(() => setLeaving(true), SPLASH_MS - 500);
    const done = setTimeout(onDone, SPLASH_MS);
    return () => {
      clearTimeout(leave);
      clearTimeout(done);
    };
  }, [onDone]);

  return (
    <div
      className={`bk-splash${leaving ? " is-leaving" : ""}`}
      role="presentation"
      onClick={onDone}
    >
      <div className="bk-splash-glow" aria-hidden="true" />

      <div className="bk-splash-mark" aria-hidden="true">
        <svg viewBox="0 0 64 64" width="72" height="72" fill="none">
          <path
            className="bk-splash-shield"
            d="M32 6 L52 14 V30 C52 44 43 53 32 58 C21 53 12 44 12 30 V14 Z"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinejoin="round"
          />
          <path
            className="bk-splash-tick"
            d="M23 32 L29.5 38.5 L41.5 26"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>

      <p className="bk-splash-word">
        <span className="bk-splash-w1">Verified</span>
        <span className="bk-splash-w2">Call</span>
      </p>

      <p className="bk-splash-tag">Your bank, checking before your money moves.</p>

      <span className="bk-splash-bar" aria-hidden="true">
        <span />
      </span>

      <p className="bk-splash-skip">Tap to skip</p>
    </div>
  );
}
