# CAMARA Findings — ground truth for all API code

> **STATUS: PRELIMINARY (docs-derived). NOT yet observed on the wire.**
>
> Everything below marked 📄 comes from Nokia's **public documentation**, not from a real
> call. It is good enough to *write the probe scripts*. It is **not** good enough to write
> `app/camara/` clients against — standing rule 1 still holds. Values get promoted to
> ✅ **OBSERVED** only after a probe script prints them.
>
> Filled in by: PROMPT 1. Last updated 2026-08-01.

---

## Platform facts 📄

| Thing | Value |
|---|---|
| Access model | **SDK-first.** Nokia publishes a Python SDK; raw REST paths are *not* in the public docs. |
| Package | `pip install network_as_code` (Python ≥ 3.9) |
| SDK source | https://github.com/nokia/network-as-code-sdks (Apache 2.0, generated from OpenAPI via Fern) |
| Auth | **App Key**, copied from the application in the NaC console dashboard |
| Console | https://networkascode.nokia.io/console/ → your application → App Key |
| Plans | `DEFAULT` and `SIMULATOR` (public signup) |
| Docs root | https://networkascode.nokia.io/docs/getting-started |

**Consequence for PROMPT 1:** the original instruction "use httpx, no SDK wrapper, I want
the raw wire format" cannot be followed as written — the wire format is undocumented, so
hand-rolling httpx calls would mean *guessing endpoint paths*, which rule 1 forbids.
**Amended approach:** call through the SDK, and attach an `httpx` event hook to the SDK's
underlying client to dump the real request/response wire format to disk. We get the SDK's
correctness *and* the raw shapes.

---

## Sandbox test numbers 📄 — the big de-risk

The simulator exposes **deterministic phone numbers**. Demo reproducibility is therefore
not dependent on a live device, and the error paths are testable on demand.

### SIM Swap
| Number | Behaviour |
|---|---|
| `+99999991000` | SIM swap **has** occurred (200) |
| `+99999991001` | SIM swap has **not** occurred (200) |

### Location Verification
| Number | Behaviour |
|---|---|
| `+99999991000` | Device **not** in area (200) |
| `+99999991001` | Device **in** area (200) |
| `+99999991002` | **Partially** within area (200) |
| `+99999991003` | Location **unknown** (200) |
| `+99999990400` | Bad Request |
| `+99999990404` | Not Found |
| `+99999990500` | Server Error |

The `0400/0404/0500` numbers let us prove the `fallback.py` path with a *real* failure
rather than a mocked one. That is a demo asset — use it in the pitch.

---

## SIM Swap 📄

- **SDK calls:**
  ```python
  sim_swap_date = client.sim_swap.retrieve_date(phone_number="+99999991000")
  result = client.sim_swap.check(phone_number="+99999991000", max_age=1)
  ```
- **Params:** `phone_number` (str, required, `+` and country code); `max_age` (int,
  optional, 1–2400 **hours**)
- **Returns:** `retrieve_date` → datetime-ish string e.g. `"2025-06-19 09:51:44.271000+00:00"`
  or `None`. `check` → `bool`.
- **Endpoint / auth header / raw JSON:** ❓ UNKNOWN — capture in probe
- **Measured latency:** ❓ UNKNOWN
- **Limitations:** `max_age` is capped at 2400h (100 days). `None` from `retrieve_date` is
  ambiguous — never swapped vs. no data. Decide how the agent treats that.

## Number Verification 📄

- **SDK calls:** ❓ page did not render for extraction — needs manual paste
- **⚠ MAJOR RISK:** silent network authentication normally requires the handset to be on
  **mobile data** (not WiFi) and involves an operator OAuth redirect from the device
  itself. A server-side probe from a laptop may be structurally unable to complete it.
  **Confirm early.** If it can't work, we integrate 3 APIs, not 4, and say so honestly.
- **Endpoint / request / response / latency / errors:** ❓ UNKNOWN

## Location Verification 📄

- **SDK call:**
  ```python
  result = client.location.verify_v1(
      device={"phone_number": "+999991234567"},
      area={"area_type": "CIRCLE"},
      max_age=3600,
  )
  ```
  (`area` needs centre lat/long + radius — exact key names ❓ UNKNOWN, capture in probe)
- **Response fields:** `verification_result` ∈ `TRUE | FALSE | PARTIAL | UNKNOWN`;
  `match_rate` (int, only when `PARTIAL`); `last_location_time` (datetime, omitted when
  `UNKNOWN`)
- **`max_age`:** seconds (3600) — **note the unit differs from SIM Swap's hours.** Easy bug.
- **Endpoint / auth / latency:** ❓ UNKNOWN
- **Limitations:** verifies *against an area you supply* — it does **not** return a
  position. Our "device location vs claimed transaction origin" framing must be rewritten
  as "is the device within Xkm of the expected city", with the radius chosen by us.

## Device Status (Roaming / Reachability) 📄

- **SDK calls:** ❓ page did not render for extraction — needs manual paste
- Documented as covering **roaming** and **reachability**
- **Endpoint / request / response / latency / errors:** ❓ UNKNOWN
- Roaming is our headline APP-fraud signal — this one matters most. Probe it first.

---

## Open questions blocking `app/camara/`

1. Real App Key in `.env` (blocked on human — console login)
2. Whether the SIMULATOR plan covers all four APIs or only some
3. Number Verification feasibility server-side (see risk above)
4. Actual wire format + latency for all four
5. Exact `area` dict keys for Location Verification
