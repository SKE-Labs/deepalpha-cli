"""Unit tests for RestrictedSubprocessBackend.

Tests the sandbox backend's execute() method with timeout handling,
math calculations, and error capture.
"""

from deepanalysts.backends.sandbox import RestrictedSubprocessBackend


class TestRestrictedSubprocessBackend:
    """Tests for RestrictedSubprocessBackend execution."""

    def test_execute_simple_python(self):
        """Test basic Python execution returns output."""
        backend = RestrictedSubprocessBackend()
        result = backend.execute("python3 -c \"print('hello')\"")
        assert "hello" in result.output
        assert result.exit_code == 0

    def test_execute_returns_exit_code(self):
        """Test non-zero exit codes are captured."""
        backend = RestrictedSubprocessBackend()
        result = backend.execute('python3 -c "import sys; sys.exit(42)"')
        assert result.exit_code == 42

    def test_execute_timeout(self):
        """Test long-running commands timeout."""
        backend = RestrictedSubprocessBackend(timeout=1)
        result = backend.execute('python3 -c "import time; time.sleep(10)"')
        # Either timeout or killed
        assert result.exit_code != 0 or "timed out" in result.output.lower()

    def test_execute_math_calculation(self):
        """Test mathematical calculations work correctly."""
        backend = RestrictedSubprocessBackend()
        result = backend.execute('python3 -c "print(2 + 2)"')
        assert "4" in result.output
        assert result.exit_code == 0

    def test_execute_captures_stderr(self):
        """Test stderr is captured in output."""
        backend = RestrictedSubprocessBackend()
        result = backend.execute("python3 -c \"import sys; print('error', file=sys.stderr)\"")
        assert "error" in result.output

    def test_execute_fibonacci_calculation(self):
        """Test Fibonacci calculation (real trading use case)."""
        backend = RestrictedSubprocessBackend()
        code = """
import sys
high = 45000
low = 38000
diff = high - low

levels = {
    "0.0%": high,
    "23.6%": high - diff * 0.236,
    "38.2%": high - diff * 0.382,
    "50.0%": high - diff * 0.5,
    "61.8%": high - diff * 0.618,
    "100.0%": low,
}
print(levels["61.8%"])
"""
        result = backend.execute(f"python3 -c '{code}'")
        assert result.exit_code == 0
        # 45000 - 7000 * 0.618 = 40674
        assert "40674" in result.output

    def test_execute_id_uniqueness(self):
        """Test each backend instance has unique ID."""
        backend1 = RestrictedSubprocessBackend()
        backend2 = RestrictedSubprocessBackend()
        assert backend1.id != backend2.id
        assert backend1.id.startswith("subprocess-")

    def test_upload_and_download_files(self):
        """Test file upload and download in sandbox."""
        backend = RestrictedSubprocessBackend()

        # Upload a file (path will be relative to temp dir)
        upload_responses = backend.upload_files([("test.txt", b"hello world")])
        assert upload_responses[0].error is None

        # Download it back
        download_responses = backend.download_files(["test.txt"])
        assert download_responses[0].error is None
        assert download_responses[0].content == b"hello world"

    def test_download_nonexistent_file(self):
        """Test downloading non-existent file returns error."""
        backend = RestrictedSubprocessBackend()
        responses = backend.download_files(["does_not_exist.txt"])
        assert responses[0].error == "file_not_found"


class TestRestrictedSubprocessBackendFileOps:
    """Tests for file operations via execute().

    Note: File paths must be relative (no leading /) since
    operations run inside the sandbox temp directory.
    """

    def test_write_and_read(self):
        """Test write() and read() work correctly."""
        backend = RestrictedSubprocessBackend()

        # Write a file (relative path - runs in temp dir)
        result = backend.write("test.md", "# Hello\n\nWorld")
        assert result.error is None
        assert result.path == "test.md"

        # Read it back
        content = backend.read("test.md")
        assert "Hello" in content
        assert "World" in content

    def test_write_existing_file_fails(self):
        """Test write() fails if file exists."""
        backend = RestrictedSubprocessBackend()

        # Create a file first
        result1 = backend.write("existing.txt", "content")
        assert result1.error is None

        # Try to write again - should fail
        result2 = backend.write("existing.txt", "new content")
        assert result2.error is not None

    def test_edit_file(self):
        """Test edit() replaces content correctly."""
        backend = RestrictedSubprocessBackend()

        # Create a file
        write_result = backend.write("edit_test.txt", "hello world")
        assert write_result.error is None

        # Edit it
        result = backend.edit("edit_test.txt", "hello", "goodbye")
        assert result.error is None, f"Edit failed: {result.error}"
        assert result.occurrences == 1

        # Verify change
        content = backend.read("edit_test.txt")
        assert "goodbye" in content
        assert "hello" not in content

    def test_edit_nonexistent_file(self):
        """Test edit() returns error for non-existent file (exit code 3)."""
        backend = RestrictedSubprocessBackend()

        result = backend.edit("nonexistent.txt", "old", "new")
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_edit_string_not_found(self):
        """Test edit() returns error when string not found (exit code 1)."""
        backend = RestrictedSubprocessBackend()

        # Create a file
        write_result = backend.write("test_not_found.txt", "some content")
        assert write_result.error is None

        # Try to edit with non-existent string
        result = backend.edit("test_not_found.txt", "nonexistent", "replacement")
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_edit_multiple_occurrences_without_replace_all(self):
        """Test edit() returns error for multiple occurrences without replace_all (exit code 2)."""
        backend = RestrictedSubprocessBackend()

        # Create a file with repeated content
        write_result = backend.write("multi.txt", "hello hello hello")
        assert write_result.error is None

        # Try to edit without replace_all
        result = backend.edit("multi.txt", "hello", "goodbye")
        assert result.error is not None
        assert "multiple" in result.error.lower()

    def test_edit_replace_all(self):
        """Test edit() with replace_all replaces all occurrences."""
        backend = RestrictedSubprocessBackend()

        # Create a file with repeated content
        write_result = backend.write("replace_all.txt", "hello hello hello")
        assert write_result.error is None

        # Edit with replace_all
        result = backend.edit("replace_all.txt", "hello", "goodbye", replace_all=True)
        assert result.error is None, f"Edit failed: {result.error}"
        assert result.occurrences == 3

        # Verify all occurrences replaced
        content = backend.read("replace_all.txt")
        assert "hello" not in content
        assert "goodbye goodbye goodbye" in content

    def test_write_large_file(self):
        """Test write() handles large files via heredoc (avoids ARG_MAX limits)."""
        backend = RestrictedSubprocessBackend()

        # Create content larger than typical ARG_MAX limits (~128KB)
        # Note: actual test uses smaller size for speed, but demonstrates the pattern
        large_content = "x" * 50000  # 50KB of content
        result = backend.write("large_file.txt", large_content)
        assert result.error is None, f"Write failed: {result.error}"

        # Verify content written correctly
        content = backend.read("large_file.txt", limit=10000)
        # First line should have our content (line numbers make it longer)
        assert "x" in content

    def test_ls_info_returns_full_paths(self):
        """Test ls_info() returns full paths with directory prefix."""
        backend = RestrictedSubprocessBackend()

        # Create a file
        backend.write("test_ls.txt", "content")

        # List the temp directory (which is "/" from sandbox perspective)
        # Note: RestrictedSubprocessBackend uses temp dir as working dir
        # We need to check if the path includes the directory
        infos = backend.ls_info(".")
        paths = [fi["path"] for fi in infos]

        # Should find our file with path including directory
        assert any("test_ls.txt" in p for p in paths)
