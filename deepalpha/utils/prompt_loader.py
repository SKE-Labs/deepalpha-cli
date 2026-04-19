"""Prompt loader — reads markdown prompt files with YAML frontmatter.

Prompts are stored as markdown files in deepalpha/prompts/ with optional YAML
frontmatter for metadata (name, version, description). The loader supports:

- Variable interpolation: {variable_name} in prompt content
- Include directives: {{include components/chart_workflow.md}} for shared sections
- Composition: load and concatenate multiple prompts (e.g., base + type-specific)
"""

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_INCLUDE_RE = re.compile(r"\{\{include\s+([\w/.\-]+)\}\}")


def _read_prompt_file(path: Path) -> str:
    """Read a prompt file, stripping YAML frontmatter if present."""
    text = path.read_text(encoding="utf-8")

    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :]

    return text.strip()


def _resolve_includes(content: str, base_dir: Path, _seen: set[str] | None = None) -> str:
    """Recursively resolve {{include path/to/file.md}} directives."""
    if _seen is None:
        _seen = set()

    def _replacer(match: re.Match) -> str:
        rel_path = match.group(1)
        if rel_path in _seen:
            logger.warning("Circular include detected: %s", rel_path)
            return f"<!-- circular include: {rel_path} -->"

        include_path = base_dir / rel_path
        if not include_path.exists():
            logger.warning("Include file not found: %s", include_path)
            return f"<!-- include not found: {rel_path} -->"

        _seen.add(rel_path)
        included = _read_prompt_file(include_path)
        return _resolve_includes(included, base_dir, _seen)

    return _INCLUDE_RE.sub(_replacer, content)


@lru_cache(maxsize=64)
def _load_raw(rel_path: str) -> str:
    """Load and cache a raw prompt (with includes resolved, before variable interpolation)."""
    path = _PROMPTS_DIR / rel_path
    try:
        content = _read_prompt_file(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {path}") from None
    content = _resolve_includes(content, _PROMPTS_DIR)
    return content


def load_prompt(rel_path: str, **variables: str) -> str:
    """Load a prompt file, resolve includes, and interpolate variables.

    Args:
        rel_path: Path relative to deepalpha/prompts/ (e.g., "analysts/supervisor.md")
        **variables: Key-value pairs for {variable} interpolation in the prompt content.
                    Only applied when variables are provided — prompts with literal braces
                    (e.g., {HOLD|CLOSED}) are safe when loaded without variables.

    Returns:
        The fully resolved prompt string.

    Example:
        prompt = load_prompt("system/env_local.md", cwd="/home/user/project")
    """
    raw = _load_raw(rel_path)
    if variables:
        raw = raw.format(**variables)
    return raw


def compose_prompt(*rel_paths: str, **variables: str) -> str:
    """Load and concatenate multiple prompt files.

    Args:
        *rel_paths: Paths relative to deepalpha/prompts/
        **variables: Applied after concatenation.

    Returns:
        The concatenated and interpolated prompt string.

    Example:
        prompt = compose_prompt("spawns/base.md", "spawns/monitoring.md")
    """
    parts = [_load_raw(p) for p in rel_paths]
    combined = "\n\n".join(parts)
    if variables:
        combined = combined.format(**variables)
    return combined
