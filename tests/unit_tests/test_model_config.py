"""Unit tests for model configuration and discovery."""

import pytest

from embient.model_config import _PROVIDER_ENV_VARS, get_available_models, has_provider_credentials


class TestGetAvailableModels:
    def test_has_all_providers(self) -> None:
        models = get_available_models()
        assert "openai" in models
        assert "anthropic" in models
        assert "google" in models

    def test_non_empty_lists(self) -> None:
        for provider, model_list in get_available_models().items():
            assert len(model_list) >= 1, f"{provider} has no models"

    def test_models_are_strings(self) -> None:
        for provider, model_list in get_available_models().items():
            for model in model_list:
                assert isinstance(model, str) and len(model) > 0, f"Invalid model in {provider}: {model!r}"


class TestHasProviderCredentials:
    def test_with_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        assert has_provider_credentials("openai") is True

    def test_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert has_provider_credentials("openai") is False

    def test_empty_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert has_provider_credentials("openai") is False

    def test_unknown_provider(self) -> None:
        assert has_provider_credentials("unknown") is None

    def test_each_provider_has_env_var(self) -> None:
        assert _PROVIDER_ENV_VARS["openai"] == "OPENAI_API_KEY"
        assert _PROVIDER_ENV_VARS["anthropic"] == "ANTHROPIC_API_KEY"
        assert _PROVIDER_ENV_VARS["google"] == "GOOGLE_API_KEY"
