"use client";

/**
 * The fraud analyst's view, laid out as a case file.
 *
 * The reasoning is the product, so the reasoning gets the width. An earlier version put
 * a seven-column table across the top and squeezed the trace into a third of the screen,
 * which pushed the page 360px past the viewport and buried the one thing a judge or an
 * analyst actually reads. Now the docket of decisions is a narrow rail and the selected
 * case opens in full beside it.
 *
 * Two rules this screen does not bend:
 *   1. A cached signal is always labelled cached. Never imply a fallback was live.
 *   2. A channel nobody checked is drawn as unknown, never as barred. Unproven and
 *      compromised are different claims and the picture has to say which one it means.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import AnalystCall from "../../components/AnalystCall";
import ChannelRoutes from "../../components/ChannelRoutes";
import LocationGap, { positionFrom } from "../../components/LocationGap";
import ScoreBar from "../../components/ScoreBar";
import {
  API_BASE,
  type DecisionDetail,
  type DecisionRow,
  clock,
  getDecision,
  listDecisions,
  money,
} from "../../lib/api";

/** One-line summary of the outcome, in the words a person would use. */
const VERDICT_LINE: Record<string, string> = {
  approve: "Let through. Nothing here justified making the customer wait.",
  intervene: "Held. The money has not moved while we check with the customer.",
  decline: "Blocked. The money has not moved.",
};

type TabId = "why" | "reach" | "call" | "evidence" | "yours";

/** Each tab says what is behind it before you open it, so nobody has to click through
 *  four panels to find where the interesting thing is. */
const TABS: {
  id: TabId;
  label: string;
  show: (d: DecisionDetail) => boolean;
  badge: (d: DecisionDetail) => React.ReactNode;
}[] = [
  {
    id: "why",
    label: "Why",
    show: () => true,
    badge: (d) => <span className="tab-count">{d.risk_score}</span>,
  },
  {
    id: "reach",
    label: "Reach",
    show: (d) => d.channels !== null,
    badge: (d) =>
      d.channels ? (
        <span
          className="tab-dot"
          data-state={d.channels.no_safe_channel ? "barred" : "open"}
        />
      ) : null,
  },
  {
    id: "call",
    label: "Call",
    show: (d) => d.voice_call !== null,
    badge: (d) =>
      d.voice_call?.outcome ? (
        <span
          className="tab-dot"
          data-state={d.voice_call.outcome === "scam_detected" ? "barred" : "open"}
        />
      ) : null,
  },
  {
    id: "evidence",
    label: "Evidence",
    show: () => true,
    badge: (d) => <span className="tab-count">{d.signal_calls.length}</span>,
  },
  {
    id: "yours",
    label: "Your call",
    show: () => true,
    // Amber until somebody has looked at it. A case nobody has reviewed is the one
    // thing on this screen that is waiting on a person rather than on the system.
    badge: (d) =>
      d.analyst_review ? (
        <span className="tab-dot" data-state={d.analyst_review.action === "released" ? "open" : "barred"} />
      ) : (
        <span className="tab-dot" data-state="todo" />
      ),
  },
];

const VERDICT: Record<string, string> = {
  approve: "approved",
  intervene: "held",
  decline: "blocked",
};

export default function Dashboard() {
  const [rows, setRows] = useState<DecisionRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DecisionDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const page = await listDecisions(40);
      setRows(page.items);
      setError(null);
      setSelected((current) => current ?? page.items[0]?.decision_id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load decisions.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Live feed. Reconnection is handled by EventSource itself; we only track the light.
  useEffect(() => {
    const es = new EventSource(`${API_BASE}/stream/decisions`);
    es.addEventListener("connected", () => setConnected(true));
    es.addEventListener("keepalive", () => setConnected(true));
    es.addEventListener("decision", () => void load());
    es.addEventListener("message", (event) => {
      // The voice layer publishes on the default event type.
      try {
        const data = JSON.parse((event as MessageEvent).data);
        if (data?.kind === "voice") void load();
      } catch {
        /* a malformed frame is not worth breaking the screen over */
      }
    });
    es.onerror = () => setConnected(false);
    return () => es.close();
  }, [load]);

  // A new decision arriving mid-demo should select itself — the analyst is watching for
  // it, and making them click the row they just watched appear is friction for nothing.
  const seen = useRef<Set<string>>(new Set());
  useEffect(() => {
    const incoming = rows.map((r) => r.decision_id).filter((id) => !seen.current.has(id));
    const isFirstLoad = seen.current.size === 0;
    rows.forEach((r) => seen.current.add(r.decision_id));
    if (isFirstLoad || incoming.length === 0) return;

    setFresh(new Set(incoming));
    setSelected(incoming[0]);
    const timer = setTimeout(() => setFresh(new Set()), 2000);
    return () => clearTimeout(timer);
  }, [rows]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    getDecision(selected)
      .then((d) => !cancelled && setDetail(d))
      .catch(() => !cancelled && setDetail(null));
    return () => {
      cancelled = true;
    };
  }, [selected, rows]);

  const flagged = rows.filter((r) => r.outcome !== "approve").length;
  const cached = rows.filter((r) => r.used_fallback).length;
  const median = medianOf(rows.map((r) => r.total_latency_ms));
  const cachedPct = rows.length ? Math.round((cached / rows.length) * 100) : 0;

  return (
    <>
      <div className="topbar" style={{ borderTop: "1px solid var(--line)" }}>
        <span className="live">
          <span className="dot" data-on={connected} />
          {connected ? "live" : "reconnecting"}
        </span>
        <span className="spacer" />
      </div>

      <main>
        {/* The four figures used to be small mono text in the top bar, where nobody
            looked. They are the credibility of this screen — particularly the cached
            one — so they are tiles, and the masthead has room to be a masthead. */}
        <header className="masthead">
          <div>
            <h1>Decision log</h1>
            <p className="sub">
              Every payment assessed, every signal pulled, and why.
            </p>
          </div>
          <div className="tiles">
            <Tile n={String(rows.length)} l="assessed" />
            <Tile n={String(flagged)} l="held or blocked" />
            <Tile n={median === null ? "—" : `${Math.round(median)}ms`} l="median" />
            <Tile n={`${cachedPct}%`} l="cached" good={cachedPct === 0} />
          </div>
        </header>

        {error && (
          <div className="siege" style={{ marginBottom: "1.25rem" }}>
            <span className="siege-title">Cannot reach the API</span>
            <p>{error}</p>
          </div>
        )}

        <div className="case">
          <div className="docket">
            <p className="docket-head">Decisions · newest first</p>
            {rows.map((r) => (
              <button
                type="button"
                key={r.decision_id}
                className={`docket-row${fresh.has(r.decision_id) ? " new-row" : ""}`}
                data-selected={r.decision_id === selected}
                data-o={r.outcome}
                onClick={() => setSelected(r.decision_id)}
              >
                <span className="docket-amount">
                  {Number(r.amount).toLocaleString("en-AE")}
                </span>
                <span className="docket-time">{clock(r.decided_at)}</span>
                <span className="docket-payee">{r.merchant_name}</span>
                <span className="docket-what">
                  <span className="badge" data-o={r.outcome}>
                    {VERDICT[r.outcome] ?? r.outcome}
                  </span>
                  <span className="route-by">
                    {r.risk_score} · {r.signals_pulled} checks
                  </span>
                  {r.analyst_action && (
                    <span className="docket-mark" data-act={r.analyst_action}>
                      {r.analyst_action}
                    </span>
                  )}
                </span>
              </button>
            ))}
            {rows.length === 0 && !error && (
              <div className="card card-pad empty">
                Nothing assessed yet. Submit a payment from the bank app.
              </div>
            )}
          </div>

          <div>
            {detail ? (
              <Case
                key={detail.decision_id}
                detail={detail}
                onReviewed={(d) => { setDetail(d); void load(); }}
              />
            ) : (
              <div className="card card-pad empty">Choose a decision to open it.</div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}

function Tile({ n, l, good }: { n: string; l: string; good?: boolean }) {
  return (
    <div className="tile" data-good={good}>
      <span className="tile-n">{n}</span>
      <span className="tile-l">{l}</span>
    </div>
  );
}

function Case({
  detail,
  onReviewed,
}: {
  detail: DecisionDetail;
  onReviewed: (updated: DecisionDetail) => void;
}) {
  const t = detail.transaction;
  const position = positionFrom(detail.signal_calls);

  // Reset to the first tab when a different case is opened. Without the key on
  // decision_id, selecting a new row would leave you on a tab that may not exist on it.
  const [open, setOpen] = useState<TabId>("why");

  return (
    <div style={{ display: "grid", gap: "1.1rem" }}>
      <div className="card card-pad case-head">
        {/* The verdict runs the full width and carries its own colour. It used to be a
            badge the same size as the latency figure, which gave the single most
            important fact on the screen no more weight than a millisecond count. */}
        <div className="verdict" data-o={detail.outcome}>
          <span className="verdict-word">{VERDICT[detail.outcome] ?? detail.outcome}</span>
          <span className="verdict-why">{VERDICT_LINE[detail.outcome] ?? ""}</span>
          {detail.analyst_review && (
            <span className="docket-mark" data-act={detail.analyst_review.action}>
              analyst {detail.analyst_review.action}
            </span>
          )}
        </div>

        <div>
          <p className="case-amount">
            {money(t.amount, t.currency)}{" "}
            <span className="to">to {t.merchant_name}</span>
          </p>
          <p style={{ margin: "0.35rem 0 0", color: "var(--muted)", fontSize: "0.86rem" }}>
            Payee {t.beneficiary_id}
            {t.is_new_beneficiary ? ", never paid before" : ", paid before"} · customer
            speaks {t.customer_locale}
          </p>
        </div>

        <div className="case-facts">
          <span className="tag">score {detail.risk_score} of 100</span>
          <span className="tag">{Math.round(detail.total_latency_ms)}ms</span>
          <span className="tag">
            {detail.signal_calls.length} of 7 checks
          </span>
          {detail.used_fallback && (
            <span className="tag" data-warn="true">
              some signals cached
            </span>
          )}
        </div>

        {t.demo_seam && (
          <div className="seam">
            <strong>Simulator seam.</strong> Network signals were looked up against{" "}
            <span className="num">{t.signal_msisdn}</span>, a Nokia sandbox number, while
            a call would go to <span className="num">{t.customer_msisdn}</span>. Sandbox
            numbers are not real phones and a real phone has no sandbox signals. In
            production these are the same number.
          </div>
        )}

      <nav className="tabs" role="tablist" aria-label="Case sections">
        {TABS.filter((tab) => tab.show(detail)).map((tab) => (
          <button
            key={tab.id}
            role="tab"
            type="button"
            className="tab"
            aria-selected={open === tab.id}
            onClick={() => setOpen(tab.id)}
          >
            {tab.label}
            {tab.badge(detail)}
          </button>
        ))}
      </nav>

      <div className="tabpanel" role="tabpanel">
        {open === "why" && (
          <div style={{ display: "grid", gap: "1.1rem" }}>
            <ScoreBar
              score={detail.risk_score}
              outcome={detail.outcome}
              trace={detail.reasoning_trace}
            />
            <ol className="trace">
              {detail.reasoning_trace.map((step) => (
                <li className="step" key={step.step} data-kind={step.kind}>
                  <span className="n">{String(step.step).padStart(2, "0")}</span>
                  <span>
                    <div className="observed">{step.observed}</div>
                    <div className="why">{step.rationale}</div>
                    {step.signal && (
                      <div style={{ marginTop: "0.4rem", display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                        <span className="tag">{step.signal.replace(/_/g, " ")}</span>
                        {step.source && (
                          <span className="tag" data-warn={step.source === "fallback"}>
                            {step.source === "fallback" ? "cached, not live" : "live"}
                          </span>
                        )}
                        {step.latency_ms !== null && (
                          <span className="tag">{Math.round(step.latency_ms)}ms</span>
                        )}
                      </div>
                    )}
                  </span>
                  <span className="delta" data-up={step.score_delta > 0}>
                    {step.score_delta > 0 ? `+${step.score_delta}` : step.score_delta || ""}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {open === "reach" && detail.channels && (
          <div style={{ display: "grid", gap: "1.1rem" }}>
            <ChannelRoutes channels={detail.channels} bare />
            {position && <LocationGap position={position} />}
          </div>
        )}

        {open === "call" && detail.voice_call && (
          <div style={{ display: "grid", gap: "0.8rem" }}>
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              <span className="tag">{detail.voice_call.language}</span>
              <span className="tag">{detail.voice_call.status}</span>
              {detail.voice_call.outcome && (
                <span
                  className="badge"
                  data-o={
                    detail.voice_call.outcome === "confirmed_legitimate"
                      ? "approve"
                      : detail.voice_call.outcome === "scam_detected"
                        ? "decline"
                        : "intervene"
                  }
                >
                  {detail.voice_call.outcome.replace(/_/g, " ")}
                </span>
              )}
              {detail.voice_call.is_mock && (
                <span className="tag" data-warn="true">simulated call</span>
              )}
              {detail.voice_call.duration_s !== null && (
                <span className="tag">{detail.voice_call.duration_s}s</span>
              )}
            </div>
            <div className="qa">
              {Object.entries(detail.voice_call.answers ?? {}).map(([key, answer]) => (
                <div className="qa-row" key={key}>
                  <span className="q">{key.replace(/_/g, " ")}</span>
                  <span className="a">
                    {answer.reply}
                    {answer.keypad ? " (keypad)" : ""}
                    {answer.hesitant ? ` · hesitated ${answer.response_ms}ms` : ""}
                  </span>
                </div>
              ))}
            </div>
            {detail.voice_call.transcript && (
              <p style={{ color: "var(--muted)", fontSize: "0.93rem", margin: 0 }}>
                {detail.voice_call.transcript}
              </p>
            )}
          </div>
        )}

        {open === "evidence" && (
          <div className="sig">
            {detail.signal_calls.map((sc) => (
              <div className="sig-row" key={sc.id}>
                <div className="sig-head">
                  <span className="sig-name">{sc.api_name.replace(/_/g, " ")}</span>
                  <span className="tag" data-warn={sc.source === "fallback"}>
                    {sc.source === "fallback" ? "cached, not live" : "live"}
                  </span>
                  <span className="tag">{Math.round(sc.latency_ms)}ms</span>
                  {msisdnOf(sc.request_payload) && (
                    <span className="route-by">{msisdnOf(sc.request_payload)}</span>
                  )}
                </div>
                {sc.fallback_reason && (
                  <p style={{ margin: "0.4rem 0 0", fontSize: "0.86rem", color: "var(--hold)" }}>
                    {sc.fallback_reason}
                  </p>
                )}
                <pre className="raw">{JSON.stringify(sc.response_payload)}</pre>
              </div>
            ))}
            {detail.signal_calls.length === 0 && (
              <p style={{ color: "var(--muted)", fontSize: "0.95rem", margin: 0 }}>
                The agent decided no network check was worth the customer&apos;s time.
              </p>
            )}
          </div>
        )}

        {open === "yours" && (
          <AnalystCall detail={detail} onReviewed={onReviewed} />
        )}
        </div>
      </div>
    </div>
  );
}

/** Which number this particular question was asked of.
 *
 *  Worth surfacing because a demo persona may source different signals from different
 *  sandbox numbers — no single simulator number can express some combinations that are
 *  ordinary in real life. Showing it per row means the seam is visible in the evidence
 *  itself rather than only in a banner someone has to believe. */
function msisdnOf(payload: Record<string, unknown>): string | null {
  const direct = payload?.phoneNumber;
  if (typeof direct === "string") return direct;
  const device = payload?.device as { phoneNumber?: unknown } | undefined;
  return typeof device?.phoneNumber === "string" ? device.phoneNumber : null;
}

function medianOf(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
