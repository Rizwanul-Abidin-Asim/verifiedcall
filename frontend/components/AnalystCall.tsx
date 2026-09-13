"use client";

/**
 * The human in the loop: release or block a payment the agent has already ruled on.
 *
 * This is the only control on the fraud desk. Everything else is evidence, and evidence
 * should not look clickable — so this is the one place with a filled button.
 *
 * The reason is required, and that is a product decision rather than a validation
 * default. A fraud team's overrides are the only dataset that tells it whether the agent
 * is calibrated: every release is either the model being too cautious or a customer who
 * was talked round after the call, and six months later nobody can tell those apart from
 * a timestamp alone.
 *
 * Note what this does NOT do: it never edits the agent's verdict. Both sit on the record,
 * and where they disagree the screen says so.
 */

import { useState } from "react";

import {
  type AnalystAction,
  type AnalystReview,
  ApiError,
  type DecisionDetail,
  type Outcome,
  reviewDecision,
} from "../lib/api";

const VERDICT: Record<Outcome, string> = {
  approve: "let through",
  intervene: "held",
  decline: "blocked",
};

function when(iso: string) {
  return new Date(iso).toLocaleString("en-GB", {
    hour12: false, day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
}

/** True when the analyst went against the agent rather than confirming it. */
function disagrees(outcome: Outcome, action: AnalystAction) {
  return action === "released" ? outcome !== "approve" : outcome === "approve";
}

function Settled({ review, outcome }: { review: AnalystReview; outcome: Outcome }) {
  return (
    <div className="review-done" data-act={review.action}>
      <span className="review-done-head">
        {review.action === "released"
          ? "Released by an analyst"
          : "Blocked by an analyst"}
      </span>
      <p className="review-done-why">{review.reason}</p>
      <span className="review-done-when">{when(review.reviewed_at)}</span>
      {disagrees(outcome, review.action) && (
        <p className="review-conflict">
          This overrides the agent, which {VERDICT[outcome]} this payment. Both are kept
          on the record — the agent&apos;s decision is not rewritten by a review.
        </p>
      )}
    </div>
  );
}

export default function AnalystCall({
  detail,
  onReviewed,
}: {
  detail: DecisionDetail;
  onReviewed: (updated: DecisionDetail) => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<AnalystAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (detail.analyst_review) {
    return <Settled review={detail.analyst_review} outcome={detail.outcome} />;
  }

  async function decide(action: AnalystAction) {
    setBusy(action);
    setError(null);
    try {
      onReviewed(await reviewDecision(detail.decision_id, action, reason.trim()));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "The review could not be saved."
      );
    } finally {
      setBusy(null);
    }
  }

  const ready = reason.trim().length >= 3 && busy === null;

  return (
    <div className="review">
      <div className="review-field">
        <label className="review-label" htmlFor="review-reason">
          What do you know that the agent did not?
        </label>
        <input
          id="review-reason"
          className="review-input"
          value={reason}
          maxLength={500}
          placeholder="Customer called back on a verified line and confirmed the transfer"
          onChange={(e) => setReason(e.target.value)}
          disabled={busy !== null}
        />
      </div>

      <div className="review-actions">
        <button
          type="button"
          className="review-btn"
          data-act="released"
          disabled={!ready}
          onClick={() => decide("released")}
        >
          {busy === "released" ? "Releasing…" : "Release this payment"}
        </button>
        <button
          type="button"
          className="review-btn"
          data-act="blocked"
          disabled={!ready}
          onClick={() => decide("blocked")}
        >
          {busy === "blocked" ? "Blocking…" : "Block it"}
        </button>
      </div>

      {error ? (
        <p className="review-conflict" style={{ color: "var(--barred)" }}>{error}</p>
      ) : (
        <p className="section-note">
          Recorded against this decision and shown beside it. A case can be reviewed
          once.
        </p>
      )}
    </div>
  );
}
