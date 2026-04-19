"""Test importing files."""


def test_imports() -> None:
    """Test importing deepalpha modules."""
    from deepalpha import (
        agent,  # noqa: F401
        integrations,  # noqa: F401
    )
    from deepalpha.main import cli_main  # noqa: F401
