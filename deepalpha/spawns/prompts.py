"""Spawn agent prompts — dynamic composition per spawn type.

Prompts are loaded from markdown files in deepalpha/prompts/spawns/.
Architecture: base prompt (shared) + type-specific prompt (monitoring / task).
"""

from deepalpha.utils.prompt_loader import compose_prompt

SPAWN_PROMPTS: dict[str, tuple[str, ...]] = {
    "monitoring": ("spawns/base.md", "spawns/monitoring.md"),
    "task": ("spawns/base.md", "spawns/task.md"),
}


def get_spawn_prompt(spawn_type: str) -> str:
    """Return the composed prompt for a given spawn type.

    Raises KeyError if spawn_type is unknown.
    """
    if spawn_type not in SPAWN_PROMPTS:
        raise KeyError(f"Unknown spawn_type '{spawn_type}'. Available types: {list(SPAWN_PROMPTS.keys())}")
    return compose_prompt(*SPAWN_PROMPTS[spawn_type])
