import pytest

from vt_pron.config import Settings


def test_ignores_the_api_port_in_a_shared_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_PORT", "8080")
    monkeypatch.setenv("VT_PRON_BASE_URL", "http://pron:8001")

    assert Settings(_env_file=None).port == 8001


def test_reads_its_own_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_PRON_PORT", "9001")

    assert Settings(_env_file=None).port == 9001
