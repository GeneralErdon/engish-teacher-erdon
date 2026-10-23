import json
from pathlib import Path

import pytest

from vt_api import openapi


def test_schema_is_deterministic_and_lists_the_llm_api() -> None:
    first, second = openapi.schema_json(), openapi.schema_json()

    assert first == second
    assert first.endswith("}\n")
    assert "/v1/llm/settings" in json.loads(first)["paths"]


def test_writes_to_a_file(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    openapi.main([str(target)])

    assert target.read_text(encoding="utf-8") == openapi.schema_json()


def test_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    openapi.main([])

    assert capsys.readouterr().out == openapi.schema_json()


def test_reads_the_command_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "schema.json"
    monkeypatch.setattr("sys.argv", ["vt-api-openapi", str(target)])

    openapi.main()

    assert target.exists()
