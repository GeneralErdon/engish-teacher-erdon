from typing import Any

import pytest
import uvicorn

from vt_pron import __main__ as entrypoint


def test_runs_uvicorn_with_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setenv("VT_PRON_PORT", "9001")

    entrypoint.main()

    assert calls == [
        (
            ("vt_pron.app:create_app",),
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 9001,
                "log_level": "info",
                "server_header": False,
            },
        )
    ]
