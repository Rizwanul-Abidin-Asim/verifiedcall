"use client";

/**
 * The fraud analyst's view.
 *
 * The reasoning trace is the point of this screen, not the score. Judges and analysts
 * both care more about whether a decision can be explained than about how clever the
 * model was, so the trace gets the most space and is rendered as a readable narrative
 * rather than a JSON dump.
 *
 * The other rule: a cached signal is always labelled as cached. We never let the screen
 * imply that a fallback response came from the live network.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  API_BASE,
  type DecisionDetail,
  type DecisionRow,
  clock,
  getDecision,
  listDecisions,
  money,
} from "../../lib/api";

export default function Dashboard() {
  const [rows, setRows] = useState<DecisionRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DecisionDetail | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const source = useRef<EventSource | null>(null);

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
    source.current = es;
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
    return () => {
      es.close();
      source.current = null;
    };
  }, [load]);

  // Flash newly arrived rows so an analyst sees what changed.
  const seen = useRef<Set<string>>(new Set());
  useEffect(() => {
    const incoming = rows.map((r) => r.decision_id).filter((id) => !seen.current.has(id));
    if (seen.current.size > 0 && incoming.length > 0) {
      setFresh(new Set(incoming));
      const timer = setTimeout(() => setFresh(new Set()), 1800);
      rows.forEach((r) => seen.current.add(r.decision_id));
      return () => clearTimeout(timer);
    }
    rows.forEach((r) => seen.current.add(r.decision_id));
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

  return (
    <>
      <div className="topbar" style={{ borderTop: "1px solid var(--line)" }}>
        <span className="live">
          <span className="dot" data-on={connected} />
          {connected ? "live" : "reconnecting"}
        </span>
        <span className="spacer" />
        <span className="tag">{rows.length} decisions</span>
      </div>

      <main>
        <p className="eyebrow">Fraud operations</p>
        <h1>Decision log</h1>
        <p className="sub">
          Every payment evaluated, every signal pulled, and why each decision was
          reached. Cached responses are labelled as cached.
        </p>

        {error && (
          <div className="result" data-o="error" style={{ marginBottom: "1.25rem" }}>
            <h2>Cannot reach the API</h2>
            <p>{error}</p>
          </div>
        )}

        <div className="stats">
          <Stat n={String(rows.length)} l="decisions" />
          <Stat n={String(flagged)} l="held or blocked" />
          <Stat n={median === null ? "—" : `${Math.round(median)}ms`} l="median latency" />
          <Stat
            n={rows.length ? `${Math.round((cached / rows.length) * 100)}%` : "—"}
            l="used cached data"
          />
        </div>

        <div className="split">
          <div className="card" style={{ overflow: "hidden" }}>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Amount</th>
                  <th>Payee</th>
                  <th>Outcome</th>
                  <th className="num">Score</th>
                  <th className="num">Checks</th>
                  <th className="num">Latency</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.decision_id}
                    onClick={() => setSelected(r.decision_id)}
                    data-selected={r.decision_id === selected}
                    className={fresh.has(r.decision_id) ? "new-row" : undefined}
                  >
                    <td className="num">{clock(r.decided_at)}</td>
                    <td className="num">{money(r.amount, r.currency)}</td>
                    <td>
                      {r.merchant_name}
                      {r.is_new_beneficiary && (
                        <>
                          {" "}
                          <span className="tag" data-warn="true">
                            first time
                          </span>
                        </>
                      )}
                    </td>
                    <td>
                      <span className="badge" data-o={r.outcome}>
                        {r.outcome === "intervene" ? "hold + call" : r.outcome}
                      </span>
                      {r.voice_outcome && (
                        <>
                          {" "}
                          <span className="tag">{r.voice_outcome.replace(/_/g, " ")}</span>
                        </>
                      )}
                    </td>
                    <td className="num">{r.risk_score}</td>
                    <td className="num">{r.signals_pulled}</td>
                    <td className="num">
                      {Math.round(r.total_latency_ms)}ms
                      {r.used_fallback && (
                        <>
                          {" "}
                          <span className="tag" data-warn="true">
                            cached
                          </span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && !error && (
                  <tr>
                    <td colSpan={7}>
                      <div className="empty">
                        No decisions yet. Submit a payment from the checkout page.
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div>{detail ? <Detail detail={detail} /> : <div className="card card-pad empty">Select a decision.</div>}</div>
        </div>
      </main>
    </>
  );
}

function Stat({ n, l }: { n: string; l: string }) {
  return (
    <div className="stat">
      <div className="n">{n}</div>
      <div className="l">{l}</div>
    </div>
  );
}

function Detail({ detail }: { detail: DecisionDetail }) {
  const t = detail.transaction;
  return (
    <div style={{ display: "grid", gap: "1.1rem" }}>
      <div className="card card-pad">
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
          <span className="badge" data-o={detail.outcome}>
            {detail.outcome === "intervene" ? "hold + call" : detail.outcome}
          </span>
          <strong className="num" style={{ fontSize: "1.15rem" }}>
            {money(t.amount, t.currency)}
          </strong>
          <span className="tag">score {detail.risk_score}</span>
          <span className="tag">{Math.round(detail.total_latency_ms)}ms</span>
        </div>
        <p style={{ margin: "0.6rem 0 0", color: "var(--muted)", fontSize: "0.9rem" }}>
          {t.merchant_name} · payee {t.beneficiary_id}
          {t.is_new_beneficiary ? " (first time)" : ""} · language {t.customer_locale}
        </p>

        {t.demo_seam && (
          <div className="seam" style={{ marginTop: "0.8rem" }}>
            <strong>Demo seam.</strong> Network signals were looked up against{" "}
            <span className="num">{t.signal_msisdn}</span>, a Nokia sandbox number, while
            a call would go to <span className="num">{t.customer_msisdn}</span>. Sandbox
            numbers are not real phones and a real phone has no sandbox signals. In
            production these are the same number.
          </div>
        )}
      </div>

      <div className="card card-pad">
        <p className="eyebrow">How this decision was reached</p>
        <ol className="trace">
          {detail.reasoning_trace.map((step) => (
            <li className="step" key={step.step} data-kind={step.kind}>
              <span className="n">{step.step}</span>
              <span>
                <div className="observed">{step.observed}</div>
                <div className="why">{step.rationale}</div>
                {step.signal && (
                  <div style={{ marginTop: "0.35rem", display: "flex", gap: "0.35rem" }}>
                    <span className="tag">{step.signal}</span>
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

      {detail.voice_call && (
        <div className="card card-pad">
          <p className="eyebrow">Verification call</p>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.6rem" }}>
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
              <span className="tag" data-warn="true">
                simulated call
              </span>
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
            <p style={{ color: "var(--muted)", fontSize: "0.86rem", marginTop: "0.7rem" }}>
              {detail.voice_call.transcript}
            </p>
          )}
        </div>
      )}

      <div className="card card-pad">
        <p className="eyebrow">Network signals ({detail.signal_calls.length})</p>
        <div className="sig">
          {detail.signal_calls.map((s) => (
            <div className="sig-row" key={s.id}>
              <div className="sig-head">
                <span className="sig-name">{s.api_name}</span>
                <span className="tag" data-warn={s.source === "fallback"}>
                  {s.source === "fallback" ? "cached, not live" : "live"}
                </span>
                <span className="tag">{Math.round(s.latency_ms)}ms</span>
              </div>
              {s.fallback_reason && (
                <p style={{ margin: "0.4rem 0 0", fontSize: "0.8rem", color: "var(--hold)" }}>
                  {s.fallback_reason}
                </p>
              )}
              <pre className="raw">{JSON.stringify(s.response_payload)}</pre>
            </div>
          ))}
          {detail.signal_calls.length === 0 && (
            <p style={{ color: "var(--muted)", fontSize: "0.88rem", margin: 0 }}>
              The agent decided no network check was worth the customer&apos;s time.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function medianOf(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
