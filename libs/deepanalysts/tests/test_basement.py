"""Unit tests for Basement API loaders.

Tests BasementSkillsLoader writing skills and assets to store.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from deepanalysts.backends.basement import BasementSkillsLoader
from deepanalysts.backends.store import StoreBackend
from langgraph.store.memory import InMemoryStore


def make_mock_runtime(store: InMemoryStore) -> MagicMock:
    """Create a mock ToolRuntime with a given store for testing StoreBackend."""
    runtime = MagicMock()
    runtime.store = store
    runtime.config = {"configurable": {"user_id": "test-user-123"}}
    return runtime


def make_store_backend(store: InMemoryStore) -> StoreBackend:
    """Create a StoreBackend with a given store for testing."""
    return StoreBackend(make_mock_runtime(store))


@pytest.mark.anyio
async def test_basement_skills_loader_writes_to_store():
    """Test BasementSkillsLoader writes skills to store."""
    # Mock Basement API response
    mock_skills = [
        {
            "name": "test-skill",
            "path": "/skills/test-skill",
            "content": "# Test Skill\nThis is a test.",
            "target_agents": ["technical_analyst"],
            "assets": [],
        }
    ]

    # Use real InMemoryStore for integrated test
    store = InMemoryStore()

    # Mock JWT and user_id
    jwt_token = "test-jwt"
    user_id = "test-user-123"

    # Initialize loader with real store
    loader = BasementSkillsLoader(
        store=store,
        token_provider=lambda: jwt_token,
    )

    # Patch basement_client.get_active_skills
    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        # Call load_skills
        await loader.load_skills(agent_name="technical_analyst", user_id=user_id)

        # Verify write to store using StoreBackend
        backend = make_store_backend(store)

        # Skills are stored WITHOUT /skills/ prefix (CompositeBackend adds it back)
        # So ls("/") should show the skill directory
        infos = backend.ls_info("/")
        paths = [fi["path"] for fi in infos]
        assert "/test-skill/" in paths

        # ls in the skill directory should show SKILL.md
        infos = backend.ls_info("/test-skill/")
        paths = [fi["path"] for fi in infos]
        assert "/test-skill/SKILL.md" in paths

        # read_file equivalent should work
        content = backend.read("/test-skill/SKILL.md")
        assert "# Test Skill" in content


@pytest.mark.anyio
async def test_basement_skills_loader_assets_to_store():
    """Test BasementSkillsLoader writes assets to store."""
    # Mock Basement API response with assets
    mock_skills = [
        {
            "name": "asset-skill",
            "path": "/skills/asset-skill",
            "content": "# Asset Skill",
            "target_agents": ["technical_analyst"],
            "assets": [
                {
                    "path": "script.py",
                    "type": "script",
                    "storage_path": "users/123/skill/script.py",
                },
                {
                    "path": "image.png",
                    "type": "image",
                    "storage_path": "users/123/skill/image.png",
                },
            ],
        }
    ]

    store = InMemoryStore()
    jwt_token = "jwt"
    user_id = "test-user-123"

    loader = BasementSkillsLoader(
        store=store,
        token_provider=lambda: jwt_token,
        supabase_url="https://test.supabase.co",
    )

    with (
        patch(
            "deepanalysts.backends.basement.basement_client.get_active_skills",
            new_callable=AsyncMock,
        ) as mock_get_skills,
        patch.object(BasementSkillsLoader, "_download_asset", new_callable=AsyncMock) as mock_download,
    ):
        mock_get_skills.return_value = mock_skills
        mock_download.return_value = "print('hello')"

        await loader.load_skills(agent_name="technical_analyst", user_id=user_id)

        # Verify files using StoreBackend (paths without /skills/ prefix)
        backend = make_store_backend(store)

        infos = backend.ls_info("/asset-skill/")
        paths = [fi["path"] for fi in infos]

        assert "/asset-skill/SKILL.md" in paths
        assert "/asset-skill/script.py" in paths
        assert "/asset-skill/image.png.ref" in paths

        # Verify content of script.py
        script_content = backend.read("/asset-skill/script.py")
        assert "print('hello')" in script_content

        # Verify .ref file content
        ref_content = backend.read("/asset-skill/image.png.ref")
        assert "image.png" in ref_content


@pytest.mark.anyio
async def test_basement_skills_loader_filters_by_agent():
    """Test BasementSkillsLoader filters skills by target_agents."""
    mock_skills = [
        {
            "name": "shared-skill",
            "path": "/skills/shared-skill",
            "content": "# Shared Skill",
            "target_agents": [],  # Empty = all agents
            "assets": [],
        },
        {
            "name": "ta-only-skill",
            "path": "/skills/ta-only-skill",
            "content": "# TA Only",
            "target_agents": ["technical_analyst"],
            "assets": [],
        },
        {
            "name": "other-skill",
            "path": "/skills/other-skill",
            "content": "# Other",
            "target_agents": ["fundamental_analyst"],
            "assets": [],
        },
    ]

    store = InMemoryStore()
    jwt_token = "jwt"
    user_id = "test-user-123"

    loader = BasementSkillsLoader(
        store=store,
        token_provider=lambda: jwt_token,
    )

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        # Load for technical_analyst
        skills = await loader.load_skills(agent_name="technical_analyst", user_id=user_id)

        # Should get shared-skill and ta-only-skill, but NOT other-skill
        skill_names = [s["name"] for s in skills]
        assert "shared-skill" in skill_names
        assert "ta-only-skill" in skill_names
        assert "other-skill" not in skill_names


@pytest.mark.anyio
async def test_basement_skills_loader_wildcard_target():
    """Test BasementSkillsLoader handles wildcard target_agents."""
    mock_skills = [
        {
            "name": "wildcard-skill",
            "path": "/skills/wildcard-skill",
            "content": "# Wildcard Skill",
            "target_agents": ["*"],  # Wildcard = all agents
            "assets": [],
        },
    ]

    store = InMemoryStore()
    jwt_token = "jwt"

    loader = BasementSkillsLoader(
        store=store,
        token_provider=lambda: jwt_token,
    )

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        # Should match any agent due to wildcard
        skills = await loader.load_skills(agent_name="any_agent", user_id="test-user-123")

        assert len(skills) == 1
        assert skills[0]["name"] == "wildcard-skill"


@pytest.mark.anyio
async def test_basement_skills_loader_no_token():
    """Test BasementSkillsLoader returns empty list when no token."""
    loader = BasementSkillsLoader(
        store=InMemoryStore(),
        token_provider=lambda: None,  # No token
    )

    skills = await loader.load_skills(agent_name="technical_analyst")

    assert skills == []


@pytest.mark.anyio
async def test_basement_skills_loader_caching():
    """Test BasementSkillsLoader caches API responses."""
    mock_skills = [
        {
            "name": "cached-skill",
            "path": "/skills/cached-skill",
            "content": "# Cached",
            "target_agents": [],
            "assets": [],
        }
    ]

    store = InMemoryStore()
    jwt_token = "jwt"

    loader = BasementSkillsLoader(
        store=store,
        token_provider=lambda: jwt_token,
    )

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        # First call should hit API
        await loader.load_skills(agent_name="ta", user_id="user1")
        assert mock_get_skills.call_count == 1

        # Second call should use cache
        await loader.load_skills(agent_name="fa", user_id="user1")
        assert mock_get_skills.call_count == 1  # Still 1

        # Clear cache and call again
        loader.clear_cache()
        await loader.load_skills(agent_name="ta", user_id="user1")
        assert mock_get_skills.call_count == 2
