"""Unit tests for SkillsMiddleware dual-loading (loader + backend/sources)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from deepanalysts.middleware.skills import SkillMetadata, SkillsMiddleware


@pytest.fixture
def mock_runtime() -> MagicMock:
    """Create a mock Runtime."""
    runtime = MagicMock()
    runtime.context = {}
    runtime.stream_writer = MagicMock()
    runtime.store = None
    del runtime.config
    return runtime


@pytest.fixture
def mock_config() -> dict:
    """Create a mock RunnableConfig."""
    return {"configurable": {"user_id": "test-user"}}


def _make_skill(name: str, description: str, path: str) -> SkillMetadata:
    """Create a SkillMetadata dict for testing."""
    return SkillMetadata(
        name=name,
        description=description,
        path=path,
        license=None,
        compatibility=None,
        metadata={},
        allowed_tools=[],
    )


class TestSkillsMiddlewareDualLoading:
    """Tests for the dual loader + backend/sources merging behavior."""

    @pytest.mark.anyio
    async def test_loader_only(self, mock_runtime: MagicMock, mock_config: dict) -> None:
        """Test that loader-only mode works (no backend/sources)."""
        api_skill = _make_skill("api-skill", "From API", "/skills/api-skill/SKILL.md")
        loader = AsyncMock()
        loader.load_skills = AsyncMock(return_value=[api_skill])

        middleware = SkillsMiddleware(loader=loader, agent_name="orchestrator")

        state: dict[str, Any] = {"messages": []}
        result = middleware.before_agent(state, mock_runtime, mock_config)

        # Sync before_agent doesn't use loader — returns empty
        assert result is not None
        assert result["skills_metadata"] == []

    @pytest.mark.anyio
    async def test_async_loader_only(self, mock_runtime: MagicMock, mock_config: dict) -> None:
        """Test that async loader-only mode works (no backend/sources)."""
        api_skill = _make_skill("api-skill", "From API", "/skills/api-skill/SKILL.md")
        loader = AsyncMock()
        loader.load_skills = AsyncMock(return_value=[api_skill])

        middleware = SkillsMiddleware(loader=loader, agent_name="orchestrator")

        state: dict[str, Any] = {"messages": []}
        result = await middleware.abefore_agent(state, mock_runtime, mock_config)

        assert result is not None
        skills = result["skills_metadata"]
        assert len(skills) == 1
        assert skills[0]["name"] == "api-skill"

    @pytest.mark.anyio
    async def test_backend_only(self, mock_runtime: MagicMock, mock_config: dict, tmp_path: Any) -> None:
        """Test that backend-only mode works (no loader)."""
        # Create a skill directory structure on disk
        skill_dir = tmp_path / "skills" / "disk-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: disk-skill\ndescription: From disk\n---\nContent")

        from deepanalysts.backends import FilesystemBackend

        backend = FilesystemBackend()
        middleware = SkillsMiddleware(backend=backend, sources=[str(tmp_path / "skills")])

        state: dict[str, Any] = {"messages": []}
        result = await middleware.abefore_agent(state, mock_runtime, mock_config)

        assert result is not None
        skills = result["skills_metadata"]
        assert len(skills) == 1
        assert skills[0]["name"] == "disk-skill"

    @pytest.mark.anyio
    async def test_dual_loading_merges_loader_and_backend(
        self, mock_runtime: MagicMock, mock_config: dict, tmp_path: Any
    ) -> None:
        """Test that both loader and backend skills are merged."""
        # API skill via loader
        api_skill = _make_skill("api-skill", "From API", "/skills/api-skill/SKILL.md")
        loader = AsyncMock()
        loader.load_skills = AsyncMock(return_value=[api_skill])

        # Disk skill via backend
        skill_dir = tmp_path / "skills" / "disk-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: disk-skill\ndescription: From disk\n---\nContent")

        from deepanalysts.backends import FilesystemBackend

        backend = FilesystemBackend()
        middleware = SkillsMiddleware(
            loader=loader,
            agent_name="orchestrator",
            backend=backend,
            sources=[str(tmp_path / "skills")],
        )

        state: dict[str, Any] = {"messages": []}
        result = await middleware.abefore_agent(state, mock_runtime, mock_config)

        assert result is not None
        skills = result["skills_metadata"]
        skill_names = {s["name"] for s in skills}
        assert "api-skill" in skill_names
        assert "disk-skill" in skill_names
        assert len(skills) == 2

    @pytest.mark.anyio
    async def test_dual_loading_api_takes_precedence(
        self, mock_runtime: MagicMock, mock_config: dict, tmp_path: Any
    ) -> None:
        """Test that API skills override backend skills with same name."""
        # API skill with name "shared-skill"
        api_skill = _make_skill("shared-skill", "API version", "/api/shared-skill/SKILL.md")
        loader = AsyncMock()
        loader.load_skills = AsyncMock(return_value=[api_skill])

        # Disk skill with same name
        skill_dir = tmp_path / "skills" / "shared-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: shared-skill\ndescription: Disk version\n---\nContent")

        from deepanalysts.backends import FilesystemBackend

        backend = FilesystemBackend()
        middleware = SkillsMiddleware(
            loader=loader,
            agent_name="orchestrator",
            backend=backend,
            sources=[str(tmp_path / "skills")],
        )

        state: dict[str, Any] = {"messages": []}
        result = await middleware.abefore_agent(state, mock_runtime, mock_config)

        assert result is not None
        skills = result["skills_metadata"]
        # Only one skill with this name
        shared = [s for s in skills if s["name"] == "shared-skill"]
        assert len(shared) == 1
        # API version wins
        assert shared[0]["description"] == "API version"

    @pytest.mark.anyio
    async def test_skips_if_already_in_state(self, mock_runtime: MagicMock, mock_config: dict) -> None:
        """Test that loading is skipped if skills_metadata already in state."""
        loader = AsyncMock()
        loader.load_skills = AsyncMock(return_value=[])

        middleware = SkillsMiddleware(loader=loader, agent_name="orchestrator")

        state: dict[str, Any] = {"messages": [], "skills_metadata": []}
        result = await middleware.abefore_agent(state, mock_runtime, mock_config)

        # Should return None (skip loading)
        assert result is None
        loader.load_skills.assert_not_called()
