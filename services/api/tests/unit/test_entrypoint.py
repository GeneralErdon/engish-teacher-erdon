from typing import Any

import pytest
import uvicorn

from vt_api import __main__ as entrypoint


def test_runs_uvicorn_with_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setenv("VT_PORT", "9090")
    monkeypatch.setenv("VT_LOG_LEVEL", "DEBUG")

    entrypoint.main()

    assert calls == [
        (
            ("vt_api.main:create_app",),
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 9090,
                "log_level": "debug",
                "server_header": False,
            },
        )
    ]
