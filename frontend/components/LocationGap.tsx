"use client";

/**
 * Where the network puts the handset, against where the payment claims to be.
 *
 * Drawn rather than mapped, on purpose. A tile map means a request to a third party in
 * the middle of a live demo, and the one thing this panel has to do is not fail on
 * stage. It also does not need geography: the finding is the GAP, and a number of
 * kilometres between two named places says that better than two pins on a map of Europe
 * nobody will look at closely.
 *
 * Only rendered when location retrieval actually ran. Retrieval is the more invasive of
 * the two location calls — it discloses a position rather than confirming one — so the
 * agent only makes it once a payment is already heading for a hold or a decline.
 */

import type { SignalCall } from "../lib/api";

/** Where the payment says the customer is. Matches expected_city on the request. */
const CLAIMED = { name: "Dubai", latitude: 25.2048, longitude: 55.2708 };

interface Position {
  latitude: number;
  longitude: number;
  radiusM: number | null;
}

/** Pull the position out of the raw Location Retrieval payload, if it was called. */
export function positionFrom(signals: SignalCall[]): Position | null {
  const call = signals.find((s) => s.api_name === "location_retrieval");
  if (!call) return null;

  const body = call.response_payload as
    | { area?: { center?: { latitude?: unknown; longitude?: unknown }; radius?: unknown } }
    | null;
  const centre = body?.area?.center;
  if (typeof centre?.latitude !== "number" || typeof centre?.longitude !== "number") {
    return null;
  }
  return {
    latitude: centre.latitude,
    longitude: centre.longitude,
    radiusM: typeof body?.area?.radius === "number" ? body.area.radius : null,
  };
}

/** Great-circle distance in km. Rounded hard: the sandbox's position is a simulated
 *  point and quoting it to the metre would imply a precision we do not have. */
function kmBetween(a: Position, b: { latitude: number; longitude: number }) {
  const R = 6371;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.latitude - a.latitude);
  const dLon = rad(b.longitude - a.longitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.latitude)) * Math.cos(rad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export default function LocationGap({ position }: { position: Position }) {
  const km = kmBetween(position, CLAIMED);
  const far = km > 100;

  return (
    <div className="gap" data-far={far}>
      <div className="gap-side">
        <span className="gap-label">Network puts the handset</span>
        <span className="gap-coord">
          {position.latitude.toFixed(3)}, {position.longitude.toFixed(3)}
        </span>
        {position.radiusM && (
          <span className="gap-note">accurate to about {position.radiusM}m</span>
        )}
      </div>

      <div className="gap-span" aria-hidden="true">
        <span className="gap-line" />
        <span className="gap-distance">{km < 1 ? "<1" : Math.round(km).toLocaleString()} km</span>
        <span className="gap-line" />
      </div>

      <div className="gap-side gap-side-end">
        <span className="gap-label">Payment claims</span>
        <span className="gap-coord">{CLAIMED.name}</span>
        <span className="gap-note">
          {CLAIMED.latitude.toFixed(3)}, {CLAIMED.longitude.toFixed(3)}
        </span>
      </div>

      <p className="gap-verdict">
        {far
          ? "The handset is not where this payment says it is. That points away from a "
            + "customer being talked into it and towards somebody else operating the "
            + "account — which is why this declines rather than triggering a call."
          : "The handset is where this payment says it is. That does not make the "
            + "payment safe; it means the customer is present, so a conversation can "
            + "settle what a decline cannot."}
      </p>
    </div>
  );
}
