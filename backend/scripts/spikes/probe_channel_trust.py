"""Phase 2 spike: the three APIs the channel-trust layer needs.

Device Reachability Status is the important one: it returns connectivity as a list of
SMS / DATA, which is per-channel rather than a single "is this risky" boolean. The
simulator exposes four distinct numbers (spec examples, Single-NaC-API-OAS.yaml):

    +99999991000  reachable, SMS only
    +99999991001  reachable, DATA only
    +99999991002  reachable, DATA and SMS
    +99999991003  not reachable

Device Swap is v1 (not v0 like SIM Swap) and takes maxAge in hours like SIM Swap.

Usage:  uv run python scripts/spikes/probe_channel_trust.py
"""

from _probe_common import probe

DSWAP = "/passthrough/camara/v1/device-swap/device-swap/v1"
REACH = "/device-status/device-reachability-status/v1/retrieve"
LOCRET = "/location-retrieval/v0/retrieve"

if __name__ == "__main__":
    # --- Device Reachability: all four simulator personas ---
    for number in ("+99999991000", "+99999991001", "+99999991002", "+99999991003"):
        probe(f"REACHABILITY {number}", REACH, {"device": {"phoneNumber": number}})

    # --- Device Swap: swapped vs not ---
    for number in ("+99999991000", "+99999991001"):
        probe(f"DEVICE SWAP check {number}", f"{DSWAP}/check",
              {"phoneNumber": number, "maxAge": 120})
    probe("DEVICE SWAP retrieve-date", f"{DSWAP}/retrieve-date",
          {"phoneNumber": "+99999991000"})

    # --- Location Retrieval: the mentor's slide-4 suggestion (returns a position,
    #     rather than verifying against one we supply) ---
    probe("LOCATION RETRIEVAL", LOCRET,
          {"device": {"phoneNumber": "+99999991000"}, "maxAge": 3600})
