/**
 * The routes to the customer, drawn rather than listed.
 *
 * Every other panel on this screen is a table or a list. This one is a picture, because
 * the thing it has to communicate is not a set of statuses — it is whether a path to a
 * person is intact, and a row of coloured badges cannot show a path being cut.
 *
 * Three states, and the third one matters as much as the other two:
 *
 *   open      the network says this route still reaches the customer
 *   barred    a named signal says somebody else is on it
 *   unknown   nobody checked — which is NOT evidence of anything
 *
 * Collapsing "unknown" into "barred" is the mistake this component exists to prevent
 * visually, the same way ChannelAssessment.no_safe_channel prevents it in the backend.
 */

import type { ChannelAssessment, ChannelVerdict } from "../lib/api";

const LABEL: Record<string, string> = {
  voice: "Call",
  sms: "Text",
  app_push: "App",
};

/** What the network was asked, in words a fraud analyst would use. */
const ASKS: Record<string, string> = {
  voice: "Would a call reach her, or someone else?",
  sms: "Would a text land on her SIM?",
  app_push: "Can the app reach her quietly?",
};

function stateOf(v: ChannelVerdict): "open" | "barred" | "unknown" {
  if (v.trusted) return "open";
  return v.blocked_by ? "barred" : "unknown";
}

function Route({ verdict, chosen }: { verdict: ChannelVerdict; chosen: boolean }) {
  const state = stateOf(verdict);
  const mark = state === "open" ? "→" : state === "barred" ? "✕" : "?";
  const words =
    state === "open" ? (chosen ? "using this" : "open") :
    state === "barred" ? "barred" : "not checked";

  return (
    <div className="route" data-state={state} data-chosen={chosen}>
      <span className="route-label">{LABEL[verdict.channel] ?? verdict.channel}</span>

      {/* aria-hidden: the line is the visual telling of what route-verdict already says
          in text, so a screen reader would otherwise hear the same fact twice. */}
      <span className="route-line" aria-hidden="true">
        <span className="route-track" />
        <span className="route-mark">{mark}</span>
      </span>

      <span className="route-verdict">
        <span className="route-state">{words}</span>
        {verdict.blocked_by && (
          <span className="route-by">{verdict.blocked_by.replace(/_/g, " ")}</span>
        )}
      </span>

      <p className="route-reason">{verdict.reason}</p>
    </div>
  );
}

export default function ChannelRoutes({
  channels,
  bare = false,
}: {
  channels: ChannelAssessment;
  /** The dashboard supplies its own card and section heading, so this renders the
   *  routes alone. Standalone use keeps the card. */
  bare?: boolean;
}) {
  const order = ["voice", "app_push", "sms"];
  const verdicts = [...channels.verdicts].sort(
    (a, b) => order.indexOf(a.channel) - order.indexOf(b.channel)
  );

  const Wrapper = bare ? "div" : "section";
  return (
    <Wrapper
      className={bare ? "" : "card card-pad"}
      style={{ display: "grid", gap: "0.9rem" }}
    >
      {!bare && (
        <p className="eyebrow" style={{ marginBottom: 0 }}>
          Can we still reach her
        </p>
      )}

      <div className="routes">
        {verdicts.map((v) => (
          <Route
            key={v.channel}
            verdict={v}
            chosen={!channels.no_safe_channel && v.channel === channels.preferred}
          />
        ))}
      </div>

      {channels.no_safe_channel ? (
        <div className="siege">
          <span className="siege-title">Every route is barred</span>
          <p>{channels.strategy}</p>
        </div>
      ) : (
        <p style={{ margin: 0, fontSize: "0.86rem", color: "var(--muted)", lineHeight: 1.55 }}>
          {channels.strategy}
        </p>
      )}

      {channels.signals_used.length > 0 && (
        <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
          <span className="route-by" style={{ alignSelf: "center" }}>asked:</span>
          {channels.signals_used.map((s) => (
            <span className="tag" key={s}>{s.replace(/_/g, " ")}</span>
          ))}
        </div>
      )}
    </Wrapper>
  );
}

export { ASKS };
