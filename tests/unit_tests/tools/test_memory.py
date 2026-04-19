"""Unit tests for memory tools (list, create, update, delete)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import ToolException

from deepalpha.trading_tools.memory import (
    create_memory,
    delete_memory,
    list_memories,
    update_memory,
)

MOCK_TOKEN = "test-jwt-token"


class TestListMemories:
    """Tests for list_memories tool."""

    def test_list_memories_no_auth(self) -> None:
        """Test that list_memories raises when not authenticated."""
        with patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=None):
            with pytest.raises(ToolException, match="Not authenticated"):
                asyncio.run(list_memories.ainvoke({}))

    def test_list_memories_api_failure(self) -> None:
        """Test that list_memories raises on API failure."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.list_memories",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            with pytest.raises(ToolException, match="Failed to fetch memories"):
                asyncio.run(list_memories.ainvoke({}))

    def test_list_memories_empty(self) -> None:
        """Test that list_memories returns message when no memories exist."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.list_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = asyncio.run(list_memories.ainvoke({}))
            assert "No memories found" in result

    def test_list_memories_with_results(self) -> None:
        """Test that list_memories formats memory data correctly."""
        memories = [
            {
                "id": "mem-1",
                "name": "Trading Style",
                "description": "My trading approach",
                "content": "Swing trader, 4H timeframe",
                "is_active": True,
            },
            {
                "id": "mem-2",
                "name": "Risk Rules",
                "content": "Max 2% per trade",
                "is_active": False,
            },
        ]
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.list_memories",
                new_callable=AsyncMock,
                return_value=memories,
            ),
        ):
            result = asyncio.run(list_memories.ainvoke({}))
            assert "Found 2 memory/memories" in result
            assert "Trading Style" in result
            assert "mem-1" in result
            assert "active" in result
            assert "Risk Rules" in result
            assert "inactive" in result

    def test_list_memories_truncates_long_content(self) -> None:
        """Test that content preview is truncated at 200 chars."""
        memories = [
            {
                "id": "mem-1",
                "name": "Long Memory",
                "content": "x" * 300,
                "is_active": True,
            },
        ]
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.list_memories",
                new_callable=AsyncMock,
                return_value=memories,
            ),
        ):
            result = asyncio.run(list_memories.ainvoke({}))
            assert "..." in result


class TestCreateMemory:
    """Tests for create_memory tool."""

    def test_create_memory_no_auth(self) -> None:
        """Test that create_memory raises when not authenticated."""
        with patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=None):
            with pytest.raises(ToolException, match="Not authenticated"):
                asyncio.run(create_memory.ainvoke({"name": "Test", "content": "Content"}))

    def test_create_memory_success(self) -> None:
        """Test successful memory creation."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.create_memory",
                new_callable=AsyncMock,
                return_value={"id": "new-mem-1"},
            ) as mock_create,
        ):
            result = asyncio.run(
                create_memory.ainvoke(
                    {
                        "name": "Trading Style",
                        "content": "Swing trader",
                        "description": "My style",
                    }
                )
            )
            assert "Memory created successfully" in result
            assert "new-mem-1" in result
            assert "Trading Style" in result
            mock_create.assert_called_once_with(
                token=MOCK_TOKEN,
                name="Trading Style",
                content="Swing trader",
                description="My style",
            )

    def test_create_memory_without_description(self) -> None:
        """Test memory creation without optional description."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.create_memory",
                new_callable=AsyncMock,
                return_value={"id": "new-mem-2"},
            ) as mock_create,
        ):
            result = asyncio.run(create_memory.ainvoke({"name": "Test", "content": "Content"}))
            assert "Memory created successfully" in result
            mock_create.assert_called_once_with(
                token=MOCK_TOKEN,
                name="Test",
                content="Content",
                description=None,
            )

    def test_create_memory_api_failure(self) -> None:
        """Test that create_memory raises on API failure."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.create_memory",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            with pytest.raises(ToolException, match="Failed to create memory"):
                asyncio.run(create_memory.ainvoke({"name": "Test", "content": "Content"}))


class TestUpdateMemory:
    """Tests for update_memory tool."""

    def test_update_memory_no_auth(self) -> None:
        """Test that update_memory raises when not authenticated."""
        with patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=None):
            with pytest.raises(ToolException, match="Not authenticated"):
                asyncio.run(update_memory.ainvoke({"memory_id": "mem-1", "content": "New content"}))

    def test_update_memory_no_fields(self) -> None:
        """Test that update_memory raises when no fields provided."""
        with patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN):
            with pytest.raises(ToolException, match="At least one field"):
                asyncio.run(update_memory.ainvoke({"memory_id": "mem-1"}))

    def test_update_memory_content(self) -> None:
        """Test updating memory content."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.update_memory",
                new_callable=AsyncMock,
                return_value={"id": "mem-1"},
            ) as mock_update,
        ):
            result = asyncio.run(update_memory.ainvoke({"memory_id": "mem-1", "content": "Updated content"}))
            assert "mem-1" in result
            assert "updated successfully" in result
            assert "content updated" in result
            mock_update.assert_called_once_with(
                token=MOCK_TOKEN,
                memory_id="mem-1",
                content="Updated content",
                name=None,
                description=None,
            )

    def test_update_memory_multiple_fields(self) -> None:
        """Test updating multiple fields at once."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.update_memory",
                new_callable=AsyncMock,
                return_value={"id": "mem-1"},
            ),
        ):
            result = asyncio.run(
                update_memory.ainvoke(
                    {
                        "memory_id": "mem-1",
                        "name": "New Name",
                        "content": "New content",
                        "description": "New desc",
                    }
                )
            )
            assert "name=New Name" in result
            assert "content updated" in result
            assert "description=New desc" in result

    def test_update_memory_api_failure(self) -> None:
        """Test that update_memory raises on API failure."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.update_memory",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            with pytest.raises(ToolException, match="Failed to update memory"):
                asyncio.run(update_memory.ainvoke({"memory_id": "mem-1", "content": "New content"}))


class TestDeleteMemory:
    """Tests for delete_memory tool."""

    def test_delete_memory_no_auth(self) -> None:
        """Test that delete_memory raises when not authenticated."""
        with patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=None):
            with pytest.raises(ToolException, match="Not authenticated"):
                asyncio.run(delete_memory.ainvoke({"memory_id": "mem-1"}))

    def test_delete_memory_success(self) -> None:
        """Test successful memory deletion."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.delete_memory",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_delete,
        ):
            result = asyncio.run(delete_memory.ainvoke({"memory_id": "mem-1"}))
            assert "mem-1" in result
            assert "deleted successfully" in result
            mock_delete.assert_called_once_with(token=MOCK_TOKEN, memory_id="mem-1")

    def test_delete_memory_api_failure(self) -> None:
        """Test that delete_memory raises on API failure."""
        with (
            patch("deepalpha.trading_tools.memory.get_jwt_token", return_value=MOCK_TOKEN),
            patch(
                "deepalpha.trading_tools.memory.basement_client.delete_memory",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            with pytest.raises(ToolException, match="Failed to delete memory"):
                asyncio.run(delete_memory.ainvoke({"memory_id": "mem-1"}))
