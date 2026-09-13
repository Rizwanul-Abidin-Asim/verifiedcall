"use client";

/**
 * How the risk score was built, as one picture.
 *
 * FORM. The job is composition and magnitude — "what made this 87?" — not change over
 * time, so this is a single stacked bar on a fixed 0-100 track rather than a waterfall.
 * Every contribution is positive, and a waterfall's floating steps buy nothing when
 * nothing ever goes down; the stack answers the question directly and survives being
 * read from the back of a room.
 *
 * COLOUR. One hue, chosen by the outcome the score landed in — green, amber or red —
 * at full strength, with a 2px surface gap between segments. Deliberately NOT a
 * light-to-dark ramp across segments: the light end of every ramp we tried fell below
 * 3:1 against white, so the first contributions would have been nearly invisible. The
 * gaps carry the composition instead, which also keeps this from inventing a fourth
 * colour meaning in an interface whose whole palette is three states.
 *
 * The status hue is never the only signal — the verdict word sits directly above it and
 * every segment is named in the list below and on hover.
 */

import type { Outcome, ReasoningStep } from "../lib/api";

const APPROVE_BELOW = 30;
const DECLINE_AT = 70;

interface Contribution {
  label: string;
  points: number;
}

/** Only steps that actually moved the number. A zero-point step is part of the
 *  narrative but not of the arithmetic, and drawing it as a sliver of nothing would
 *  claim it mattered. */
export function contributionsOf(trace: ReasoningStep[]): Contribution[] {
  return trace
    .filter((s) => s.score_delta > 0)
    .map((s) => ({ label: s.observed, points: s.score_delta }));
}

export default function ScoreBar({
  score,
  outcome,
  trace,
}: {
  score: number;
  outcome: Outcome;
  trace: ReasoningStep[];
}) {
  const parts = contributionsOf(trace);
  const counted = parts.reduce((total, p) => total + p.points, 0);

  // The score is clamped to 0-100 while the parts are not, so they can disagree on a
  // very high-risk payment. Scale the drawing to whichever is larger and say so, rather
  // than drawing a bar that overflows its own track.
  const scale = Math.max(100, counted);

  return (
    <figure className="scorebar">
      <figcaption className="scorebar-head">
        <span className="scorebar-score" data-o={outcome}>{score}</span>
        <span className="scorebar-of">of 100</span>
        <span className="scorebar-caption">
          {parts.length === 0
            ? "Nothing in this payment added risk."
            : `Built from ${parts.length} ${parts.length === 1 ? "finding" : "findings"}.`}
        </span>
      </figcaption>

      <div
        className="scorebar-track"
        role="img"
        aria-label={`Risk score ${score} out of 100, from ${parts.length} findings.`}
      >
        {parts.map((part, i) => (
          <span
            key={`${part.label}-${i}`}
            className="scorebar-seg"
            data-o={outcome}
            style={{ width: `${(part.points / scale) * 100}%` }}
            /* Native title: a tooltip that needs no library, works on keyboard focus,
               and cannot break during a demo. */
            title={`${part.label} · +${part.points}`}
          />
        ))}

        {/* Thresholds, so the number has meaning without a legend. These are the real
            constants from scoring.py, not decoration. */}
        <span className="scorebar-mark" style={{ left: `${(APPROVE_BELOW / scale) * 100}%` }}>
          <span className="scorebar-mark-label">{APPROVE_BELOW} hold</span>
        </span>
        <span className="scorebar-mark" style={{ left: `${(DECLINE_AT / scale) * 100}%` }}>
          <span className="scorebar-mark-label">{DECLINE_AT} block</span>
        </span>
      </div>
    </figure>
  );
}
