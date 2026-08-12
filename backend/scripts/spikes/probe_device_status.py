"""Phase 1 spike: CAMARA Device Status (roaming) via Nokia NaC.

Roaming + first-time beneficiary is the classic APP fraud pattern.

Usage:  uv run python scripts/spikes/probe_device_status.py [+99999991000]

Sandbox numbers: +99999991000 roaming (HU), +99999991001 home network.
"""

from _probe_common import phone_from_argv, probe

if __name__ == "__main__":
    phone = phone_from_argv("+99999991000")
    probe("DEVICE STATUS — roaming", "/device-status/device-roaming-status/v1/retrieve",
          {"device": {"phoneNumber": phone}})
