"""
exceptions.py

wiki-cli exception hierarchy. All pipeline errors inherit from
WikiCompilerError so callers can catch them without depending on internals.
"""


class WikiCompilerError(Exception):
    """Base exception for all wiki-cli errors."""


class ExtractionError(WikiCompilerError):
    """Entity extraction from a raw file failed."""


class RewriteError(WikiCompilerError):
    """Page rewriting or file output failed."""


class LintError(WikiCompilerError):
    """Lint report generation failed."""


class StoreError(WikiCompilerError):
    """Persistence layer failure."""

