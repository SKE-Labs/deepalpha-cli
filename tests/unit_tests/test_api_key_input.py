"""Unit tests for _save_api_key() — persisting API keys to ~/.embient/.env."""

import os
import stat
from pathlib import Path

import pytest

from embient.widgets.api_key_input import _save_api_key


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect Path.home() to tmp_path so writes go to a temp directory."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def _env_path(fake_home: Path) -> Path:
    return fake_home / ".embient" / ".env"


class TestSaveApiKey:
    def test_creates_env_file(self, fake_home: Path) -> None:
        _save_api_key("TEST_KEY", "test-value")
        assert _env_path(fake_home).exists()

    def test_sets_os_environ(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_KEY_2", raising=False)
        _save_api_key("TEST_KEY_2", "val123")
        assert os.environ["TEST_KEY_2"] == "val123"
        # Cleanup
        monkeypatch.delenv("TEST_KEY_2", raising=False)

    def test_writes_key_value_line(self, fake_home: Path) -> None:
        _save_api_key("OPENAI_API_KEY", "sk-test-abc")
        content = _env_path(fake_home).read_text()
        assert "OPENAI_API_KEY=sk-test-abc" in content

    def test_replaces_existing_key(self, fake_home: Path) -> None:
        env = _env_path(fake_home)
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text("OTHER_VAR=keep\nOPENAI_API_KEY=old-value\nANOTHER=also-keep\n")
        _save_api_key("OPENAI_API_KEY", "new-value")
        content = env.read_text()
        assert "OPENAI_API_KEY=new-value" in content
        assert "old-value" not in content
        assert "OTHER_VAR=keep" in content
        assert "ANOTHER=also-keep" in content

    def test_appends_new_key(self, fake_home: Path) -> None:
        env = _env_path(fake_home)
        env.parent.mkdir(parents=True, exist_ok=True)
        env.write_text("EXISTING=value\n")
        _save_api_key("NEW_KEY", "new-val")
        content = env.read_text()
        assert "EXISTING=value" in content
        assert "NEW_KEY=new-val" in content

    def test_file_permissions(self, fake_home: Path) -> None:
        _save_api_key("PERM_KEY", "secret")
        mode = _env_path(fake_home).stat().st_mode
        assert stat.S_IMODE(mode) == 0o600
