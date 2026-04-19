"""Unit tests for subscription-based LLM provider modules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Z.AI
# ---------------------------------------------------------------------------


class TestZaiProvider:
    def test_has_credentials_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "test-key")
        from deepalpha.providers.zai import has_zai_credentials

        assert has_zai_credentials() is True

    def test_has_credentials_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        from deepalpha.providers.zai import has_zai_credentials

        assert has_zai_credentials() is False

    def test_get_config_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "my-key")
        monkeypatch.delenv("ZAI_BASE_URL", raising=False)
        monkeypatch.delenv("ZAI_MODEL", raising=False)
        from deepalpha.providers.zai import ZAI_CODING_GLOBAL_URL, get_zai_config

        result = get_zai_config()
        assert result is not None
        api_key, base_url, model = result
        assert api_key == "my-key"
        assert base_url == ZAI_CODING_GLOBAL_URL
        assert model == "glm-5"

    def test_get_config_custom_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "key")
        monkeypatch.setenv("ZAI_BASE_URL", "cn")
        from deepalpha.providers.zai import ZAI_CN_URL, get_zai_config

        result = get_zai_config()
        assert result is not None
        assert result[1] == ZAI_CN_URL

    def test_get_config_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        from deepalpha.providers.zai import get_zai_config

        assert get_zai_config() is None


# ---------------------------------------------------------------------------
# Alibaba
# ---------------------------------------------------------------------------


class TestAlibabaProvider:
    def test_has_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALIBABA_API_KEY", "sk-sp-test")
        from deepalpha.providers.alibaba import has_alibaba_credentials

        assert has_alibaba_credentials() is True

    def test_get_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALIBABA_API_KEY", "sk-sp-test")
        monkeypatch.delenv("ALIBABA_BASE_URL", raising=False)
        monkeypatch.delenv("ALIBABA_MODEL", raising=False)
        from deepalpha.providers.alibaba import ALIBABA_GLOBAL_URL, get_alibaba_config

        result = get_alibaba_config()
        assert result is not None
        assert result[0] == "sk-sp-test"
        assert result[1] == ALIBABA_GLOBAL_URL
        assert result[2] == "qwen3.5-plus"

    def test_get_config_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALIBABA_API_KEY", raising=False)
        from deepalpha.providers.alibaba import get_alibaba_config

        assert get_alibaba_config() is None


# ---------------------------------------------------------------------------
# MiniMax
# ---------------------------------------------------------------------------


class TestMinimaxProvider:
    def test_has_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test")
        from deepalpha.providers.minimax import has_minimax_credentials

        assert has_minimax_credentials() is True

    def test_get_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test")
        monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
        monkeypatch.delenv("MINIMAX_MODEL", raising=False)
        from deepalpha.providers.minimax import get_minimax_config

        result = get_minimax_config()
        assert result is not None
        assert result[2] == "MiniMax-M2.5"


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------


class TestSyntheticProvider:
    def test_has_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNTHETIC_API_KEY", "test")
        from deepalpha.providers.synthetic import has_synthetic_credentials

        assert has_synthetic_credentials() is True

    def test_get_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNTHETIC_API_KEY", "test")
        monkeypatch.delenv("SYNTHETIC_BASE_URL", raising=False)
        from deepalpha.providers.synthetic import get_synthetic_config

        result = get_synthetic_config()
        assert result is not None
        assert result[1] == "https://api.synthetic.new/v1"


# ---------------------------------------------------------------------------
# Chutes
# ---------------------------------------------------------------------------


class TestChutesProvider:
    def test_has_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHUTES_API_KEY", "test")
        from deepalpha.providers.chutes import has_chutes_credentials

        assert has_chutes_credentials() is True

    def test_get_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHUTES_API_KEY", "test")
        monkeypatch.delenv("CHUTES_BASE_URL", raising=False)
        from deepalpha.providers.chutes import get_chutes_config

        result = get_chutes_config()
        assert result is not None
        assert "chutes" in result[1]


# ---------------------------------------------------------------------------
# Copilot credential store
# ---------------------------------------------------------------------------


class TestCopilotCredentialStore:
    def test_save_and_load_github_token(self, tmp_path: Path) -> None:
        from deepalpha.providers.copilot import CopilotCredentialStore

        store = CopilotCredentialStore(base_dir=tmp_path)
        store.save_github_token("ghp_test123")
        assert store.has_github_token() is True
        assert store.load_github_token() == "ghp_test123"

    def test_load_missing_token(self, tmp_path: Path) -> None:
        from deepalpha.providers.copilot import CopilotCredentialStore

        store = CopilotCredentialStore(base_dir=tmp_path)
        assert store.has_github_token() is False
        assert store.load_github_token() is None

    def test_save_and_load_copilot_token(self, tmp_path: Path) -> None:
        from deepalpha.providers.copilot import CopilotCredentialStore

        store = CopilotCredentialStore(base_dir=tmp_path)
        store.save_copilot_token("tok_abc", 1999999999.0)
        result = store.load_copilot_token()
        assert result is not None
        assert result[0] == "tok_abc"
        assert result[1] == 1999999999.0

    def test_clear(self, tmp_path: Path) -> None:
        from deepalpha.providers.copilot import CopilotCredentialStore

        store = CopilotCredentialStore(base_dir=tmp_path)
        store.save_github_token("ghp_test")
        store.save_copilot_token("tok", 9999999999.0)
        store.clear()
        assert store.has_github_token() is False
        assert store.load_copilot_token() is None

    def test_file_permissions(self, tmp_path: Path) -> None:
        from deepalpha.providers.copilot import CopilotCredentialStore

        store = CopilotCredentialStore(base_dir=tmp_path)
        store.save_github_token("ghp_test")
        token_file = tmp_path / "copilot-github.json"
        # On Unix, check permissions; on Windows this is a no-op
        import os

        if os.name != "nt":
            mode = token_file.stat().st_mode & 0o777
            assert mode == 0o600


# ---------------------------------------------------------------------------
# Copilot token utilities
# ---------------------------------------------------------------------------


class TestCopilotTokenUtils:
    def test_derive_base_url_default(self) -> None:
        from deepalpha.providers.copilot import DEFAULT_COPILOT_BASE_URL, derive_base_url_from_token

        assert derive_base_url_from_token("no-proxy-ep-here") == DEFAULT_COPILOT_BASE_URL

    def test_derive_base_url_from_proxy_ep(self) -> None:
        from deepalpha.providers.copilot import derive_base_url_from_token

        token = "tid=abc;proxy-ep=proxy.individual.githubcopilot.com;exp=123"
        assert derive_base_url_from_token(token) == "https://api.individual.githubcopilot.com"

    def test_derive_base_url_no_proxy_prefix(self) -> None:
        from deepalpha.providers.copilot import derive_base_url_from_token

        token = "tid=abc;proxy-ep=api.example.com;exp=123"
        assert derive_base_url_from_token(token) == "https://api.example.com"


# ---------------------------------------------------------------------------
# Codex credential store
# ---------------------------------------------------------------------------


class TestCodexCredentialStore:
    def test_save_and_load(self, tmp_path: Path) -> None:
        from deepalpha.providers.codex import CodexCredentialStore

        store = CodexCredentialStore(base_dir=tmp_path)
        store.save("access_tok", "refresh_tok", 9999999999.0, "acct_123")
        assert store.has_credentials() is True

        data = store.load()
        assert data is not None
        assert data["access_token"] == "access_tok"
        assert data["refresh_token"] == "refresh_tok"
        assert data["account_id"] == "acct_123"

    def test_clear(self, tmp_path: Path) -> None:
        from deepalpha.providers.codex import CodexCredentialStore

        store = CodexCredentialStore(base_dir=tmp_path)
        store.save("a", "r", 0.0)
        store.clear()
        assert store.has_credentials() is False
        assert store.load() is None


class TestCodexJwtParsing:
    def test_extract_account_id_from_jwt(self) -> None:
        import base64

        from deepalpha.providers.codex import _extract_account_id

        payload = {"chatgpt_account_id": "acct_test123"}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        token = f"header.{payload_b64}.signature"
        assert _extract_account_id(token) == "acct_test123"

    def test_extract_account_id_nested(self) -> None:
        import base64

        from deepalpha.providers.codex import _extract_account_id

        payload = {"https://api.openai.com/auth": {"chatgpt_account_id": "nested_acct"}}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        token = f"header.{payload_b64}.signature"
        assert _extract_account_id(token) == "nested_acct"

    def test_extract_account_id_from_orgs(self) -> None:
        import base64

        from deepalpha.providers.codex import _extract_account_id

        payload = {"organizations": [{"id": "org_abc"}]}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        token = f"header.{payload_b64}.signature"
        assert _extract_account_id(token) == "org_abc"

    def test_extract_account_id_invalid(self) -> None:
        from deepalpha.providers.codex import _extract_account_id

        assert _extract_account_id("invalid") is None
        assert _extract_account_id("") is None


# ---------------------------------------------------------------------------
# Gemini credential store
# ---------------------------------------------------------------------------


class TestGeminiCredentialStore:
    def test_save_and_load(self, tmp_path: Path) -> None:
        from deepalpha.providers.gemini import GeminiCredentialStore

        store = GeminiCredentialStore(base_dir=tmp_path)
        store.save("access", "refresh", 9999999999.0, email="user@example.com")
        assert store.has_credentials() is True

        data = store.load()
        assert data is not None
        assert data["access_token"] == "access"
        assert data["email"] == "user@example.com"

    def test_clear(self, tmp_path: Path) -> None:
        from deepalpha.providers.gemini import GeminiCredentialStore

        store = GeminiCredentialStore(base_dir=tmp_path)
        store.save("a", "r", 0.0)
        store.clear()
        assert store.has_credentials() is False


# ---------------------------------------------------------------------------
# _detect_provider (config.py)
# ---------------------------------------------------------------------------


class TestDetectProvider:
    def test_copilot_prefix(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("copilot/claude-sonnet-4-5-20250929") == "copilot"

    def test_codex_prefix(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("codex/gpt-5.3-codex") == "codex"

    def test_codex_model_name_routes_to_openai(self) -> None:
        """gpt-* models route to openai by default; use codex/ prefix for codex."""
        from deepalpha.config import _detect_provider

        assert _detect_provider("gpt-5.3-codex") == "openai"

    def test_openai_models(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("gpt-5-mini") == "openai"
        assert _detect_provider("o4-mini") == "openai"

    def test_anthropic(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("claude-sonnet-4-5-20250929") == "anthropic"

    def test_google(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("gemini-3-flash-preview") == "google"

    def test_zai(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("glm-5") == "zai"

    def test_alibaba(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("qwen3.5-plus") == "alibaba"

    def test_minimax(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("MiniMax-M2.5") == "minimax"

    def test_chutes(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("deepseek-ai/DeepSeek-V3-0324") == "chutes"

    def test_unknown(self) -> None:
        from deepalpha.config import _detect_provider

        assert _detect_provider("totally-unknown-model") is None


# ---------------------------------------------------------------------------
# model_config — new providers
# ---------------------------------------------------------------------------


class TestModelConfigNewProviders:
    def test_all_providers_present(self) -> None:
        from deepalpha.model_config import get_available_models

        models = get_available_models()
        expected = [
            "openai",
            "anthropic",
            "google",
            "copilot",
            "codex",
            "gemini-cli",
            "zai",
            "alibaba",
            "minimax",
            "synthetic",
            "chutes",
        ]
        for provider in expected:
            assert provider in models, f"Missing provider: {provider}"

    def test_has_provider_credentials_copilot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deepalpha.model_config import has_provider_credentials

        # No credentials file → False
        monkeypatch.setattr(
            "deepalpha.providers.copilot.CopilotCredentialStore.__init__",
            lambda self, base_dir=None: setattr(self, "_dir", tmp_path) or None,
        )
        assert has_provider_credentials("copilot") is False

        # Create the file → True
        (tmp_path / "copilot-github.json").write_text("{}")
        assert has_provider_credentials("copilot") is True

    def test_has_provider_credentials_zai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from deepalpha.model_config import has_provider_credentials

        monkeypatch.setenv("ZAI_API_KEY", "test")
        assert has_provider_credentials("zai") is True

    def test_has_provider_credentials_alibaba(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from deepalpha.model_config import has_provider_credentials

        monkeypatch.delenv("ALIBABA_API_KEY", raising=False)
        assert has_provider_credentials("alibaba") is False
        monkeypatch.setenv("ALIBABA_API_KEY", "sk-sp-test")
        assert has_provider_credentials("alibaba") is True

    def test_env_vars_for_new_providers(self) -> None:
        from deepalpha.model_config import _PROVIDER_ENV_VARS

        assert _PROVIDER_ENV_VARS["zai"] == "ZAI_API_KEY"
        assert _PROVIDER_ENV_VARS["alibaba"] == "ALIBABA_API_KEY"
        assert _PROVIDER_ENV_VARS["minimax"] == "MINIMAX_API_KEY"
        assert _PROVIDER_ENV_VARS["synthetic"] == "SYNTHETIC_API_KEY"
        assert _PROVIDER_ENV_VARS["chutes"] == "CHUTES_API_KEY"
