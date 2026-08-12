"""Phase 1 spike: CAMARA Number Verification via Nokia NaC.

KEPT DELIBERATELY, THOUGH IT FAILS. This script is evidence for the submission: it
records why Number Verification is not in our core four.

Observed 2026-08-12: HTTP 401 {"detail":"Authorization header is missing"}.

The endpoint is subscriber-scoped and needs a three-legged OIDC authorisation-code
token, which requires the handset itself to complete a redirect over mobile data.
A server-side probe structurally cannot satisfy that. We replaced it with Call
Forwarding Signal, which is a better APP-fraud signal anyway.

Usage:  uv run python scripts/spikes/probe_number_verification.py [+99999991000]
"""

from _probe_common import phone_from_argv, probe

PATH = "/passthrough/camara/v1/number-verification/number-verification/v0"

if __name__ == "__main__":
    phone = phone_from_argv("+99999991000")
    probe("NUMBER VERIFICATION — verify (expected 401)", f"{PATH}/verify",
          {"phoneNumber": phone})
