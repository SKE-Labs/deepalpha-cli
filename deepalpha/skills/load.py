"""Skill loader for CLI commands.

This module provides filesystem-based skill loading for CLI operations (list, create, info).
It wraps the prebuilt middleware functionality from the deepanalysts library and adapts
it for direct filesystem access needed by CLI commands.

For middleware usage within agents, use deepanalysts.middleware.skills.SkillsMiddleware directly.
"""

from __future__ import annotations

from pathlib import Path

from deepanalysts.backends import FilesystemBackend
from deepanalysts.middleware.skills import SkillMetadata, _list_skills as list_skills_from_backend

BUILT_IN_SKILLS_DIR = Path(__file__).parent / "built_in"


class ExtendedSkillMetadata(SkillMetadata):
    """Extended skill metadata for CLI display, adds source tracking."""

    source: str


# Re-export for CLI commands
__all__ = ["SkillMetadata", "list_skills", "BUILT_IN_SKILLS_DIR"]


def list_skills(
    *, user_skills_dir: Path | None = None, project_skills_dir: Path | None = None
) -> list[ExtendedSkillMetadata]:
    """List skills from user, project, and built-in directories.

    This is a CLI-specific wrapper around the prebuilt middleware's skill loading
    functionality. It uses FilesystemBackend to load skills from local directories.

    Loading order (lowest to highest priority):
    1. Built-in skills (shipped with deepalpha-cli)
    2. User skills (~/.deepalpha/<agent>/skills/)
    3. Project skills (.deepalpha/skills/)

    Higher priority sources override lower ones when skill names conflict.

    Args:
        user_skills_dir: Path to the user-level skills directory.
        project_skills_dir: Path to the project-level skills directory.

    Returns:
        Merged list of skill metadata from all sources, with project skills
        taking highest precedence.
    """
    all_skills: dict[str, ExtendedSkillMetadata] = {}

    # Load built-in skills first (lowest priority — user overrides win)
    if BUILT_IN_SKILLS_DIR.exists():
        builtin_backend = FilesystemBackend(root_dir=str(BUILT_IN_SKILLS_DIR))
        builtin_skills = list_skills_from_backend(backend=builtin_backend, source_path=".")
        for skill in builtin_skills:
            extended_skill: ExtendedSkillMetadata = {**skill, "source": "built-in"}
            all_skills[skill["name"]] = extended_skill

    # Load user skills second (overrides built-in)
    if user_skills_dir and user_skills_dir.exists():
        user_backend = FilesystemBackend(root_dir=str(user_skills_dir))
        user_skills = list_skills_from_backend(backend=user_backend, source_path=".")
        for skill in user_skills:
            extended_skill: ExtendedSkillMetadata = {**skill, "source": "user"}
            all_skills[skill["name"]] = extended_skill

    # Load project skills last (highest priority)
    if project_skills_dir and project_skills_dir.exists():
        project_backend = FilesystemBackend(root_dir=str(project_skills_dir))
        project_skills = list_skills_from_backend(backend=project_backend, source_path=".")
        for skill in project_skills:
            extended_skill: ExtendedSkillMetadata = {**skill, "source": "project"}
            all_skills[skill["name"]] = extended_skill

    return list(all_skills.values())
