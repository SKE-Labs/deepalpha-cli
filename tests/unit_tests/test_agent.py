"""Unit tests for agent.py — get_system_prompt()."""

from unittest.mock import patch


class TestGetSystemPrompt:
    """Tests for get_system_prompt() prompt composition."""

    @patch("deepalpha.agent.load_prompt")
    def test_local_mode(self, mock_load: object) -> None:
        mock_load.side_effect = lambda path, **kw: f"[{path}|{kw}]"

        from deepalpha.agent import get_system_prompt

        result = get_system_prompt("test-agent")
        calls = mock_load.call_args_list
        # Should load env_local.md with cwd kwarg
        env_call = calls[0]
        assert env_call[0][0] == "system/env_local.md"
        assert "cwd" in env_call[1]
        # Should load system_prompt.md with agent_dir_path
        body_call = calls[1]
        assert body_call[0][0] == "system/system_prompt.md"
        assert body_call[1]["agent_dir_path"] == "~/.deepalpha/test-agent"
        # Result combines both
        assert "\n\n" in result

    @patch("deepalpha.agent.get_default_working_dir", return_value="/workspace")
    @patch("deepalpha.agent.load_prompt")
    def test_sandbox_mode(self, mock_load: object, mock_wd: object) -> None:
        mock_load.side_effect = lambda path, **kw: f"[{path}]"

        from deepalpha.agent import get_system_prompt

        get_system_prompt("test-agent", sandbox_type="modal")
        env_call = mock_load.call_args_list[0]
        assert env_call[0][0] == "system/env_sandbox.md"
        assert env_call[1]["working_dir"] == "/workspace"

    @patch("deepalpha.agent.load_prompt")
    def test_agent_dir_path_in_body(self, mock_load: object) -> None:
        mock_load.return_value = "content"

        from deepalpha.agent import get_system_prompt

        get_system_prompt("my-agent")
        body_call = mock_load.call_args_list[1]
        assert body_call[1]["agent_dir_path"] == "~/.deepalpha/my-agent"

    @patch("deepalpha.agent.load_prompt")
    def test_result_combines_env_and_body(self, mock_load: object) -> None:
        mock_load.side_effect = ["ENV_SECTION", "BODY_SECTION"]

        from deepalpha.agent import get_system_prompt

        result = get_system_prompt("x")
        assert result == "ENV_SECTION\n\nBODY_SECTION"
