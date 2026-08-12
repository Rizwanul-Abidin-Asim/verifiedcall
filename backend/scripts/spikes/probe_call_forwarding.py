"""Phase 1 spike: CAMARA Call Forwarding Signal via Nokia NaC.

This replaced Number Verification in our core four — see docs/camara-findings.md.
Unconditional forwarding active during a payment is the strongest single APP-fraud
signal we can get, because it means the victim's calls are being intercepted.

Usage:  uv run python scripts/spikes/probe_call_forwarding.py [+99999991000]

Sandbox numbers: +99999991000 active, +99999991001 inactive, +99999991111 multi-type.
"""

from _probe_common import phone_from_argv, probe

PATH = "/passthrough/camara/v1/call-forwarding-signal/call-forwarding-signal/v0.3"

if __name__ == "__main__":
    phone = phone_from_argv("+99999991000")
    probe("CALL FORWARDING — unconditional", f"{PATH}/unconditional-call-forwardings",
          {"phoneNumber": phone})
    probe("CALL FORWARDING — all types", f"{PATH}/call-forwardings", {"phoneNumber": phone})
