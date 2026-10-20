import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's VT_* variables."""
    for name in os.environ:
        if name.startswith("VT_"):
            monkeypatch.delenv(name)
