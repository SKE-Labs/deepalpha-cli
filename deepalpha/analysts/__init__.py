"""Analyst subagent definitions for Deep Analysts workflow."""

from deepalpha.analysts.fundamental import get_fundamental_analyst
from deepalpha.analysts.graph import create_deep_analysts
from deepalpha.analysts.technical import get_technical_analyst

__all__ = [
    "create_deep_analysts",
    "get_fundamental_analyst",
    "get_technical_analyst",
]
