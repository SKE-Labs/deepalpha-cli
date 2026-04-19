"""Memory tools for managing user memories (preferences, rules, strategies)."""

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token


@tool
async def list_memories() -> str:
    """Retrieves all user memories with IDs, names, descriptions, and active status.

    Usage:
    - Call BEFORE `create_memory` to check for existing memories on the same topic
    - Call BEFORE `update_memory` or `delete_memory` to get the memory ID
    - Returns memory IDs needed for `update_memory` and `delete_memory`

    Tool references:
    - Use `create_memory` to save new preferences or rules
    - Use `update_memory` with a memory ID from this tool's output
    - Use `delete_memory` with a memory ID from this tool's output

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    memories = await basement_client.list_memories(token=token)

    if memories is None:
        raise ToolException("Failed to fetch memories from API.")

    if not memories:
        return "No memories found. You can create memories to save trading preferences, risk rules, and strategies."

    result = f"Found {len(memories)} memory/memories:\n\n"
    for mem in memories:
        status = "active" if mem.get("is_active", True) else "inactive"
        result += f"- **{mem['name']}** (ID: {mem['id']}, {status})\n"
        if mem.get("description"):
            result += f"  Description: {mem['description']}\n"
        content_preview = mem.get("content", "")
        if len(content_preview) > 200:
            content_preview = content_preview[:200] + "..."
        result += f"  Content: {content_preview}\n\n"

    return result


class CreateMemorySchema(BaseModel):
    """Arguments for create_memory tool."""

    name: str = Field(
        description="Short, descriptive name (max 100 chars, must be unique per user). "
        "Examples: 'Trading Style', 'Risk Management', 'BTC Strategy'"
    )
    content: str = Field(
        description="The memory content. Write concise, actionable rules using the user's own words. Max 50KB."
    )
    description: str | None = Field(
        default=None,
        description="Optional brief description of what this memory covers",
    )


@tool(args_schema=CreateMemorySchema)
async def create_memory(
    name: str,
    content: str,
    description: str | None = None,
) -> str:
    """Creates a new persistent memory for trading preferences, rules, or strategies.

    Usage:
    - Call `list_memories` first to check for existing memories on the same topic
    - Write content in the user's own words — concise, actionable rules
    - One memory per logical category (don't mix risk rules with indicator preferences)
    - Use specific numbers and thresholds, not vague descriptions

    NEVER:
    - Create a duplicate memory — update the existing one with `update_memory` instead
    - Paraphrase or rewrite what the user said — preserve their terminology

    IMPORTANT:
    - Max 20 memories per user
    - Max 100 characters for `name` (must be unique per user)
    - Max 50KB for `content`
    - Requires authentication. Run 'deepalpha login' first.

    Tool references:
    - Use `list_memories` first to check for duplicates
    - Use `update_memory` to modify an existing memory instead of creating a new one
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    result = await basement_client.create_memory(
        token=token,
        name=name,
        content=content,
        description=description,
    )

    if result is None:
        raise ToolException("Failed to create memory. The name may already exist or limits may be exceeded.")

    return f"Memory created successfully!\nID: {result.get('id')}\nName: {name}\nContent: {content}"


class UpdateMemorySchema(BaseModel):
    """Arguments for update_memory tool."""

    memory_id: str = Field(description="The memory ID to update (from `list_memories` output)")
    content: str | None = Field(
        default=None,
        description="New content to replace existing content. Max 50KB.",
    )
    name: str | None = Field(
        default=None,
        description="New name for the memory (max 100 chars, must be unique per user)",
    )
    description: str | None = Field(
        default=None,
        description="New description for the memory",
    )


@tool(args_schema=UpdateMemorySchema)
async def update_memory(
    memory_id: str,
    content: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> str:
    """Updates an existing memory's content, name, or description.

    Usage:
    - Call `list_memories` first to get the `memory_id`
    - Use when the user wants to modify existing preferences or add to them
    - Provide only the fields that need changing — omitted fields stay unchanged

    NEVER:
    - Update without first retrieving the memory ID from `list_memories`

    IMPORTANT:
    - At least one of `content`, `name`, or `description` must be provided
    - New `name` must still be unique per user (max 100 chars)
    - Requires authentication. Run 'deepalpha login' first.

    Tool references:
    - Use `list_memories` to find the memory ID
    - Use `delete_memory` to remove a memory entirely
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    if not any([content, name, description]):
        raise ToolException("At least one field (content, name, or description) must be provided.")

    result = await basement_client.update_memory(
        token=token,
        memory_id=memory_id,
        content=content,
        name=name,
        description=description,
    )

    if result is None:
        raise ToolException(f"Failed to update memory ID {memory_id}. It may not exist or the name may conflict.")

    updates = []
    if name:
        updates.append(f"name={name}")
    if content:
        updates.append("content updated")
    if description:
        updates.append(f"description={description}")

    return f"Memory ID {memory_id} updated successfully.\nChanges: {', '.join(updates)}"


class DeleteMemorySchema(BaseModel):
    """Arguments for delete_memory tool."""

    memory_id: str = Field(description="The memory ID to delete (from `list_memories` output)")


@tool(args_schema=DeleteMemorySchema)
async def delete_memory(memory_id: str) -> str:
    """Deletes a memory permanently.

    Usage:
    - Call `list_memories` first to get the `memory_id`
    - Use when the user explicitly asks to remove a saved preference or rule

    CRITICAL:
    - This operation cannot be undone

    NEVER:
    - Delete without first confirming with the user
    - Delete without retrieving the memory ID from `list_memories`

    IMPORTANT:
    - Requires authentication. Run 'deepalpha login' first.

    Tool references:
    - Use `list_memories` to find the memory ID
    - Use `update_memory` to modify content instead of deleting
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    success = await basement_client.delete_memory(token=token, memory_id=memory_id)

    if not success:
        raise ToolException(f"Failed to delete memory ID {memory_id}. It may not exist.")

    return f"Memory ID {memory_id} deleted successfully."
