"""Unit tests for prompt_loader — file-based prompt loading, caching, includes."""

from pathlib import Path

import pytest

from embient.utils.prompt_loader import _load_raw, compose_prompt, load_prompt


@pytest.fixture(autouse=True)
def _isolated_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect prompt loading to tmp_path and clear LRU cache between tests."""
    monkeypatch.setattr("embient.utils.prompt_loader._PROMPTS_DIR", tmp_path)
    yield
    _load_raw.cache_clear()


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    """Write a file relative to tmp_path, creating parent dirs."""
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


class TestLoadPrompt:
    """Tests for load_prompt()."""

    def test_load_simple_prompt(self, tmp_path: Path) -> None:
        _write(tmp_path, "simple.md", "Hello world")
        assert load_prompt("simple.md") == "Hello world"

    def test_strips_yaml_frontmatter(self, tmp_path: Path) -> None:
        _write(tmp_path, "fm.md", '---\nname: test\nversion: "1.0"\n---\nActual content')
        assert load_prompt("fm.md") == "Actual content"

    def test_no_frontmatter_passthrough(self, tmp_path: Path) -> None:
        _write(tmp_path, "plain.md", "No frontmatter here")
        assert load_prompt("plain.md") == "No frontmatter here"

    def test_frontmatter_with_multiline_content(self, tmp_path: Path) -> None:
        content = "---\nname: x\n---\nLine 1\n\nLine 2\nLine 3"
        _write(tmp_path, "multi.md", content)
        assert load_prompt("multi.md") == "Line 1\n\nLine 2\nLine 3"

    def test_whitespace_stripped(self, tmp_path: Path) -> None:
        _write(tmp_path, "ws.md", "\n\n  content  \n\n")
        assert load_prompt("ws.md") == "content"

    def test_variable_interpolation(self, tmp_path: Path) -> None:
        _write(tmp_path, "vars.md", "Path: {cwd}/file.py")
        assert load_prompt("vars.md", cwd="/home/user") == "Path: /home/user/file.py"

    def test_no_interpolation_without_variables(self, tmp_path: Path) -> None:
        _write(tmp_path, "braces.md", "STATUS: {HOLD|CLOSED}")
        result = load_prompt("braces.md")
        assert result == "STATUS: {HOLD|CLOSED}"

    def test_missing_prompt_file(self) -> None:
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            load_prompt("nonexistent.md")


class TestIncludeResolution:
    """Tests for {{include}} directive resolution."""

    def test_include_resolution(self, tmp_path: Path) -> None:
        _write(tmp_path, "components/footer.md", "Footer content")
        _write(tmp_path, "main.md", "Header\n\n{{include components/footer.md}}")
        result = load_prompt("main.md")
        assert "Header" in result
        assert "Footer content" in result
        assert "{{include" not in result

    def test_nested_includes(self, tmp_path: Path) -> None:
        _write(tmp_path, "c.md", "C-content")
        _write(tmp_path, "b.md", "B-before\n{{include c.md}}\nB-after")
        _write(tmp_path, "a.md", "A-start\n{{include b.md}}\nA-end")
        result = load_prompt("a.md")
        assert "A-start" in result
        assert "B-before" in result
        assert "C-content" in result
        assert "A-end" in result

    def test_circular_include(self, tmp_path: Path) -> None:
        _write(tmp_path, "loop.md", "Before\n{{include loop.md}}\nAfter")
        result = load_prompt("loop.md")
        assert "Before" in result
        assert "<!-- circular include: loop.md -->" in result

    def test_missing_include_file(self, tmp_path: Path) -> None:
        _write(tmp_path, "ref.md", "Start\n{{include missing.md}}\nEnd")
        result = load_prompt("ref.md")
        assert "Start" in result
        assert "<!-- include not found: missing.md -->" in result
        assert "End" in result


class TestComposePrompt:
    """Tests for compose_prompt()."""

    def test_compose_two_prompts(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.md", "Part A")
        _write(tmp_path, "b.md", "Part B")
        result = compose_prompt("a.md", "b.md")
        assert result == "Part A\n\nPart B"

    def test_compose_with_variables(self, tmp_path: Path) -> None:
        _write(tmp_path, "x.md", "Hello {name}")
        _write(tmp_path, "y.md", "Bye {name}")
        result = compose_prompt("x.md", "y.md", name="World")
        assert result == "Hello World\n\nBye World"


class TestCaching:
    """Tests for LRU cache behavior."""

    def test_lru_cache_hit(self, tmp_path: Path) -> None:
        _write(tmp_path, "cached.md", "cached content")
        _load_raw.cache_clear()
        load_prompt("cached.md")
        load_prompt("cached.md")
        info = _load_raw.cache_info()
        assert info.hits >= 1
        assert info.misses >= 1
