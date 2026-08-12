"""Phase 1 spike: CAMARA Location Verification via Nokia NaC.

NOTE: this verifies a device against an area WE supply. It does not return a position.

Usage:  uv run python scripts/spikes/probe_location_verification.py [+99999991000]

Sandbox numbers: +99999991000 outside, +99999991001 inside, +99999991002 partial,
+99999991003 unknown, +99999990400/0404/0500 force those HTTP errors.
"""

from _probe_common import phone_from_argv, probe

AREA = {
    "areaType": "CIRCLE",
    "center": {"latitude": 50.735851, "longitude": 7.10066},
    "radius": 50000,
}

if __name__ == "__main__":
    phone = phone_from_argv("+99999991000")
    probe("LOCATION VERIFICATION — verify", "/location-verification/v1/verify",
          {"device": {"phoneNumber": phone}, "area": AREA})
