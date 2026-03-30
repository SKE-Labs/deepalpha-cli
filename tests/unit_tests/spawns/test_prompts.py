"""Unit tests for spawn prompt loading and composition."""

import pytest

from embient.spawns.prompts import get_spawn_prompt


class TestGetSpawnPrompt:
    def test_monitoring_contains_role(self) -> None:
        prompt = get_spawn_prompt("monitoring")
        assert "Position Monitor" in prompt

    def test_task_contains_role(self) -> None:
        prompt = get_spawn_prompt("task")
        assert "Task Executor" in prompt

    def test_both_share_base(self) -> None:
        mon = get_spawn_prompt("monitoring")
        task = get_spawn_prompt("task")
        assert "Autonomous Spawn Agent" in mon
        assert "Autonomous Spawn Agent" in task
        assert "Core Principles" in mon
        assert "Core Principles" in task

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown spawn_type"):
            get_spawn_prompt("invalid")

    def test_prompts_non_empty(self) -> None:
        assert len(get_spawn_prompt("monitoring")) > 100
        assert len(get_spawn_prompt("task")) > 100
