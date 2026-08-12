"""Phase 1 spike: CAMARA SIM Swap via Nokia NaC.

Usage:  uv run python scripts/spikes/probe_sim_swap.py [+99999991000]

Sandbox numbers: +99999991000 swapped, +99999991001 not swapped.
"""

from _probe_common import phone_from_argv, probe

PATH = "/passthrough/camara/v1/sim-swap/sim-swap/v0"

if __name__ == "__main__":
    phone = phone_from_argv("+99999991000")
    probe("SIM SWAP — check", f"{PATH}/check", {"phoneNumber": phone, "maxAge": 240})
    probe("SIM SWAP — retrieve-date", f"{PATH}/retrieve-date", {"phoneNumber": phone})
