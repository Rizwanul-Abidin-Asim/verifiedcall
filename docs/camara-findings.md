# CAMARA Findings — ground truth for all API code

> **STATUS: ✅ OBSERVED.** Every shape below was recorded from a real call to the Nokia
> Network-as-Code simulator on **2026-08-12** using the probes in
> `backend/scripts/spikes/`. `app/camara/` may now be written against these.
>
> Re-run any probe to reconfirm: `uv run python scripts/spikes/probe_sim_swap.py +99999991000`

---

## Platform

| Thing | Value |
|---|---|
| Base URL | `https://network-as-code.p-eu.apihub.nokia.io` |
| Auth | **Two headers only** — no OAuth needed for our four APIs |
| | `x-rapidapi-key: <App Key from console>` |
| | `x-rapidapi-host: network-as-code.nokia.rapidapi.com` |
| Plan | Free / **Simulator mode**. Live networks need a billing account — we stay on simulator. |
| Gateway | Kong → RapidAPI, region GCP europe-west3 |
| Rate limits | **100 req/sec, 1500 req/min** (from `x-ratelimit-*` response headers) |
| Spec source | `openapi/Single-NaC-API-OAS.yaml` in github.com/nokia/network-as-code-sdks |

**Raw REST works.** The SDK is not required — earlier concern about undocumented wire
format is resolved. Use `httpx` directly.

### Measured latency (warm, single call)

| API | Observed |
|---|---|
| SIM Swap check | 404 ms → 257 ms |
| Call Forwarding | 254–358 ms |
| Roaming status | 280–539 ms |
| Location Verification | 270–352 ms |

First call after idle is ~1.1s (cold). Four calls issued **concurrently** land inside
~550ms, comfortably under the 2s approve-path budget.

---

## ✅ SIM Swap — `POST /passthrough/camara/v1/sim-swap/sim-swap/v0/...`

```
/check          {"phoneNumber":"+99999991000","maxAge":240}  → 200 {"swapped":true}
                {"phoneNumber":"+99999991001","maxAge":240}  → 200 {"swapped":false}
/retrieve-date  {"phoneNumber":"+99999991000"}
                → 200 {"latestSimChange":"2026-08-12T11:40:52.028918Z"}
```

`maxAge` is in **hours**, 1–2400. Fraud signal: recent swap ⇒ OTP-interception risk.

## ✅ Call Forwarding Signal — `POST /passthrough/camara/v1/call-forwarding-signal/call-forwarding-signal/v0.3/...`

```
/unconditional-call-forwardings  {"phoneNumber":"+99999991000"} → 200 {"active":true}
                                 {"phoneNumber":"+99999991001"} → 200 {"active":false}
/call-forwardings                {"phoneNumber":"+99999991000"}
   → 200 ["unconditional","conditional_no_answer"]
   (+99999991111 → all four types incl. conditional_busy, conditional_not_reachable)
```

**This is our highest-value signal and it replaces Number Verification.** Unconditional
forwarding active at payment time means the customer's calls are being intercepted — a
direct indicator of an in-progress scam, not merely of a compromised identity. Note the
`/call-forwardings` variant may return **501** on some operators (documented, out of the
CFS API's core scope); handle it.

## ✅ Device Status / Roaming — `POST /device-status/device-roaming-status/v1/retrieve`

```
{"device":{"phoneNumber":"+99999991000"}}
  → 200 {"device":{"phoneNumber":"+99999991000"},
         "lastStatusTime":"2026-08-12T11:50:53.268270Z",
         "roaming":true,"countryCode":36,"countryName":["HU"]}
{"device":{"phoneNumber":"+99999991001"}}
  → 200 {...,"roaming":false}          # countryCode/countryName omitted when home
```

`countryCode` is an **MCC** (36 → HU). `countryName` is a list — a single MCC can map to
several countries (e.g. 340 → BL, GF, GP, MF, MQ). Do not assume one element.

## ✅ Location Verification — `POST /location-verification/v1/verify`

```
{"device":{"phoneNumber":"+99999991001"},
 "area":{"areaType":"CIRCLE","center":{"latitude":50.735851,"longitude":7.10066},
         "radius":50000}}
  → 200 {"verificationResult":"TRUE","lastLocationTime":"2026-08-12T11:50:54.339972"}
```

`verificationResult` ∈ `TRUE | FALSE | PARTIAL | UNKNOWN`. `matchRate` (int) present only
on `PARTIAL`. `lastLocationTime` omitted on `UNKNOWN`.

**Limitation:** verifies against an area *we* supply — it does not return a position. Our
check is therefore "is the device within R metres of the expected city", radius chosen by
us. `radius` is in **metres**; note `maxAge` here is **seconds** while SIM Swap's is hours.

## ❌ Number Verification — NOT USABLE, and that is a finding

```
POST /passthrough/camara/v1/number-verification/number-verification/v0/verify
{"phoneNumber":"+99999991000"} → 401 {"detail":"Authorization header is missing"}
```

Subscriber-scoped: needs a **three-legged OIDC authorisation-code token**, which requires
the handset itself to complete a redirect **over mobile data, not WiFi**. A server-side
call structurally cannot satisfy this. `probe_number_verification.py` is kept in the repo
as evidence. Replaced by Call Forwarding Signal.

## ✅ Error behaviour — testable on demand

```
+99999990400 → 400 | +99999990404 → 404 | +99999990500 → 500 {"detail":"Internal Server Error"}
unknown path → 404 {"message":"Endpoint '/x' does not exist"}
```

These let us exercise the `fallback.py` path with a **real** failure rather than a mock.
Use `+99999990500` in the demo to show honest degradation live.

---

## Final API set — 4 APIs, 2 categories

| API | Category | Fraud signal |
|---|---|---|
| SIM Swap | Identity / anti-fraud | Recent swap ⇒ OTP interception risk |
| Call Forwarding Signal | Identity / anti-fraud | Calls being intercepted **right now** |
| Device Roaming Status | Device / network | Roaming + new beneficiary = classic APP pattern |
| Location Verification | Device / location | Device not where the transaction claims |

Satisfies the "multiple APIs" and "spanning categories" bonus criteria.
