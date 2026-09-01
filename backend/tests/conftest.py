"""Make the suite independent of whoever's .env happens to be on disk.

Settings are loaded from .env at import, so a developer switching VOICE_CHANNEL to try
a browser call silently changed what the tests exercised. That is exactly what happened:
`test_a_failed_dial_leaves_the_payment_held` started passing through the web branch and
asserting against a call that was never dialled, and the failure looked like a bug in
the code rather than in the harness.

A test suite whose result depends on an untracked file is not telling you the truth. So
every test starts from the declared defaults, and any test that wants different
behaviour says so with monkeypatch, visibly, in the test itself.
"""

import pytest

from app.config import Settings, settings

# The fields whose value changes which code path runs. Pinned to whatever the class
# declares, so this list cannot drift away from the defaults it is meant to restore.
_PINNED = ("voice_mock", "voice_channel", "demo_mode", "llm_provider")


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch):
    defaults = Settings.model_fields
    for name in _PINNED:
        if name in defaults:
            monkeypatch.setattr(settings, name, defaults[name].default)
    yield
