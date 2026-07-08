"""
wiki-cli: compile raw notes (txt, md, docx, pdf, html, ...) into a linked, linted markdown wiki.
"""

__version__ = "1.0.0"

# All modules use flat sibling imports (from extractor import ...). Ensure
# src/ is on sys.path so those resolve when importing as a package.
import os
import sys

_src = os.path.dirname(os.path.abspath(__file__))
if _src not in sys.path:
    sys.path.insert(0, _src)

from compiler import (
    ChangeDetector,
    ChangeSet,
    CompileEvent,
    CompilePlanner,
    Compiler,
    CompilerConfig,
    CompileResult,
    CompileStats,
    compile_wiki,
)
from converter import convert_to_text, is_supported, needs_conversion
from extractor import Entity
from graph import GraphBuilder, GraphBuilderResult, WordIndexGraphBuilder
from linter import LintReport, lint, print_report
from plugin import (
    Extractor,
    LinkResolver,
    MarkdownRenderer,
    Plugin,
    Renderer,
    TxtExtractor,
    Validator,
    WikiLinkResolver,
    WikiLinter,
)
from source import (
    ConvertingDocument,
    Document,
    FilesystemProvider,
    SourceProvider,
)
from store import (
    CURRENT_COMPILER_VERSION,
    CURRENT_EXTRACTOR_VERSION,
    CURRENT_TOKENIZER_VERSION,
    SCHEMA_VERSION,
    ContentRepository,
    EntityRepo,
    GraphRepo,
    IndexRepo,
    MemoryStore,
    SQLiteStore,
    StateRepo,
    Store,
    make_entity_id,
)
from watcher import watch

__all__ = [
    "ChangeDetector",
    "ChangeSet",
    "CompileEvent",
    "CompileResult",
    "CompileStats",
    "Compiler",
    "CompilerConfig",
    "watch",
    "CompilePlanner",
    "compile_wiki",
    "Extractor",
    "GraphBuilder",
    "GraphBuilderResult",
    "LinkResolver",
    "MarkdownRenderer",
    "Plugin",
    "Renderer",
    "TxtExtractor",
    "Validator",
    "WikiLinkResolver",
    "WikiLinter",
    "WordIndexGraphBuilder",
    "LintReport",
    "lint",
    "print_report",
    "Entity",
    "ConvertingDocument",
    "Document",
    "SourceProvider",
    "FilesystemProvider",
    "convert_to_text",
    "is_supported",
    "needs_conversion",
    "Store",
    "SQLiteStore",
    "MemoryStore",
    "ContentRepository",
    "EntityRepo",
    "GraphRepo",
    "IndexRepo",
    "StateRepo",
    "make_entity_id",
    "SCHEMA_VERSION",
    "CURRENT_COMPILER_VERSION",
    "CURRENT_EXTRACTOR_VERSION",
    "CURRENT_TOKENIZER_VERSION",
]
