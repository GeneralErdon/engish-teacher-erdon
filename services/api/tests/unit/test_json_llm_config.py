import json
import logging
import stat
import sys
from pathlib import Path

import anyio
import pytest
from pydantic import SecretStr

from vt_api.adapters.json_llm_config import JsonLlmConfigRepository
from vt_api.domain.llm import LlmConfig, ProviderConfig

CONFIG = LlmConfig(
    active="anthropic",
    providers={
        "anthropic": ProviderConfig(
            "anthropic", "https://api.anthropic.com", "claude-opus-5-5", SecretStr("sk-ant-1")
        ),
        "ollama": ProviderConfig("ollama", "http://localhost:11434", "gemma3", SecretStr("")),
    },
    source="saved",
)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "nested" / "settings.json"


async def test_nothing_saved(path: Path) -> None:
    assert await JsonLlmConfigRepository(path).load() is None


async def test_round_trip_keeps_the_keys(path: Path) -> None:
    repository = JsonLlmConfigRepository(path)

    await repository.save(CONFIG)
    loaded = await repository.load()

    assert loaded == CONFIG
    stored = json.loads(await anyio.Path(path).read_text())
    assert stored["providers"]["anthropic"]["api_key"] == "sk-ant-1"
    assert not await anyio.Path(path.with_name(".settings.json.tmp")).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_file_is_private(path: Path) -> None:
    await JsonLlmConfigRepository(path).save(CONFIG)

    assert stat.S_IMODE((await anyio.Path(path).stat()).st_mode) == 0o600


async def test_save_replaces_the_previous_file(path: Path) -> None:
    repository = JsonLlmConfigRepository(path)
    await repository.save(CONFIG)
    only_ollama = LlmConfig(
        active="ollama", providers={"ollama": CONFIG.providers["ollama"]}, source="saved"
    )

    await repository.save(only_ollama)

    assert await repository.load() == only_ollama


async def test_clear(path: Path) -> None:
    repository = JsonLlmConfigRepository(path)
    await repository.save(CONFIG)

    await repository.clear()
    await repository.clear()  # nothing left to delete: still fine

    assert await repository.load() is None


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"version": 2, "active": "ollama", "providers": {}}',
        '{"version": 1, "active": "openai", "providers": {}}',
    ],
)
async def test_unreadable_file_falls_back_to_the_environment(
    path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    await anyio.Path(path.parent).mkdir(parents=True)
    await anyio.Path(path).write_text(content)

    with caplog.at_level(logging.WARNING):
        assert await JsonLlmConfigRepository(path).load() is None

    assert "Ignoring unreadable LLM settings file" in caplog.text
