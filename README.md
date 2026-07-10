# wiki-cli

Compile raw notes into a linked, linted markdown wiki. Deterministic, incremental, with a persistent SQLite cache and plugin system.

![Python Version](https://img.shields.io/badge/python-3.12%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Pipeline

```
raw_notes/ (.txt, .md, .docx, .pdf, .html, …)
  │
  ├─ SourceProvider — recursive directory walk
  │   └─ non-txt files auto-converted via MarkItDown
  │
  ├─ extractor — regex entity extraction (# Title / UPPERCASE / filename fallback)
  ├─ graph — word-indexed mention matcher (no self-links; longest-first)
  ├─ relationships — multi-graph: navigation (parent/child), folder, lexical
  ├─ rewriter — section-aware markdown with ## Notes preservation
  └─ linter — broken links, duplicate titles, unreachable pages
  │
  └─ compiled_wiki/ (.md + auto index.md + index.html per directory)
```

## Features

- **11 input formats**: `.txt`, `.md`, `.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`, `.csv`, `.json`, `.xml`, `.rtf`
- **Deterministic**: same input → same output. No LLM calls.
- **Incremental**: SHA-256 hashing + 3 version constants; only changed files reprocessed
- **SQLite store**: 5 repos (Entity, Graph, Content, Index, State); survives full rebuilds
- **Recursive walk**: subdirectory structure mirrored in output
- **Watch mode**: polling-based, recompiles on file change
- **Parallel extraction**: `ProcessPoolExecutor` via `--workers N`
- **Human-owned ## Notes**: preserved across recompiles
- **Auto index**: `index.md` + `index.html` generated at every directory level
- **Relationship engine**: parent/child/sibling + lexical backlinks for ranked `## Related`
- **Navigation hubs**: Python API only — `CompilerConfig(navigation_hubs=N)` links top pages into every page
- **Graph report**: `--report` prints top-linked and unlinked entities
- **Plugin ABCs**: Extractor, Renderer, Validator, GraphBuilder, LinkResolver
- **i18n**: Unicode `\w` tokeniser handles Vietnamese / mixed content
- **Typed errors**: ExtractionError, RewriteError, LintError, StoreError (all WikiCompilerError)

## Quick Start

```bash
# One-shot: generate 20-file demo corpus and compile
python src/init.py

# CLI (all 11 formats):
wiki-cli raw_notes/                   # output defaults to raw_notes-wiki
wiki-cli raw_notes/ compiled_wiki/
wiki-cli raw_notes/ compiled_wiki/ --watch
wiki-cli raw_notes/ compiled_wiki/ --workers 4
wiki-cli raw_notes/ compiled_wiki/ --strict --report

# Module entry:
python -m src raw_notes/ compiled_wiki/

# Or directly:
python src/compiler.py raw_notes/ compiled_wiki/
```

```python
from src import Compiler, CompilerConfig, CompileEvent

config = CompilerConfig(lint=True, workers=2, strict=False)
compiler = Compiler(config=config)

# Event-driven iteration
for event in compiler.compile_events("raw_notes", "compiled_wiki"):
    if event.event == "extracted":
        print(".", end="", flush=True)

result = compiler.compile("raw_notes", "compiled_wiki")
print(f"Compiled {result.pages_written} pages")
print(f"  entities: {result.stats.entity_count}")
print(f"  edges:    {result.stats.edge_count}")
print(f"  elapsed:  {result.stats.elapsed_s:.2f}s")
if result.lint_report:
    print(f"  broken:   {len(result.lint_report.broken_links)}")
    print(f"  orphans:  {len(result.lint_report.unreachable_pages)}")
```

## CLI Reference

```
wiki-cli raw_dir [output_dir] [options]

Positional:
  raw_dir              Raw source files directory
  output_dir           Output directory (default: {raw_dir}-wiki)

Options:
  --no-lint            Skip lint pass
  --strict             Report missing created/aliases metadata
  --watch, -w          Poll for changes and recompile
  --poll-interval SEC  Poll interval in seconds (default: 1.0)
  --workers N          Parallel extraction workers (default: 1)
  --report             Print graph report after compilation
```

## Python API

```python
from src import (
    Compiler, CompilerConfig, CompileResult, CompileStats,
    compile_wiki,                   # legacy — .txt only
    Entity,
    LintReport,
    Store, SQLiteStore, MemoryStore,
    GraphBuilder, WordIndexGraphBuilder, GraphReport,
    SourceProvider, FilesystemProvider,
    RelationshipEngine,
    Plugin, Extractor, Renderer, Validator, LinkResolver,
    WikiCompilerError, ExtractionError, RewriteError, LintError,
)
```

`Compiler` is the main entry point. `compile_wiki()` is the legacy shim (only reads `.txt`).

## Output Format

Each entity → `<slug>.md` with 5 sections:

| Section | Content | Preserved on recompile |
|---------|---------|----------------------|
| `## Metadata` | created, aliases, source relpath | no |
| `## Related` | ranked entities (graph edges / relationship engine) | no |
| `## Linked From` | backlinks from other pages | no |
| `## Body` | raw note body text | no |
| `## Notes` | human-edited notes | **yes** |

`index.md` + `index.html` are generated for every directory level.

## Tests

```bash
python -m unittest src.tests -v
```

136 tests — 18 classes covering store, migrations, compiler pipeline, change detection, incremental graph, parallel extraction, plugins, watcher, source provider, converter, multi-format.

## Input Formats

| Extension | Format |
|-----------|--------|
| `.txt`    | Plain text |
| `.md`     | Markdown |
| `.docx`   | Word document |
| `.pdf`    | PDF |
| `.html`   | HTML |
| `.pptx`   | PowerPoint |
| `.xlsx`   | Excel |
| `.csv`    | CSV |
| `.json`   | JSON |
| `.xml`    | XML |
| `.rtf`    | Rich Text Format |

## Installation

```bash
git clone https://github.com/htvinh/wiki-cli.git
cd wiki-cli
pip install -e ".[dev]"       # editable + ruff + mypy
# or: pip install .            # production
```

## Project Structure

```
wiki-cli/
├── pyproject.toml
└── src/
    ├── __init__.py       # public API re-exports (Compiler, Entity, Store, …)
    ├── __main__.py       # python -m src → compiler.main()
    ├── compiler.py       # Compiler, CompilePlanner, ChangeDetector, CLI
    ├── converter.py      # MarkItDown (called internally by ConvertingDocument)
    ├── exceptions.py     # WikiCompilerError ← ExtractionError / RewriteError / LintError / StoreError
    ├── extractor.py      # stage 1: regex entity extraction (Entity dataclass)
    ├── generator.py      # deterministic synthetic corpus (random.Random(seed))
    ├── graph.py          # stage 2: word-indexed phrase matcher + GraphBuilder ABC
    ├── init.py           # zero-config demo (calls generator + compile_wiki)
    ├── linter.py         # stage 4: broken links, duplicate titles, unreachable, --strict metadata
    ├── plugin.py         # Plugin, Extractor, Renderer, Validator, LinkResolver ABCs
    ├── relationship.py   # multi-graph: navigation, folder, lexical (RelationshipEngine)
    ├── rewriter.py       # stage 3: section-aware markdown + auto index.md/index.html
    ├── source.py         # SourceProvider, FilesystemProvider, Document, ConvertingDocument
    ├── store.py          # Store ABC, SQLiteStore, MemoryStore, 5 repos, migrations
    ├── watcher.py        # polling-based file watcher
    ├── benchmark.py      # timing harness
    └── tests.py          # 136 stdlib tests
├── docs/
│   ├── spec.md
│   ├── implementation-plan.md
│   └── usage.md
└── LICENSE
```

## Edge Cases & Quirks

- **Slug convention**: `name.lower().replace(" ", "_").replace("-", "_")` everywhere
- **Entity key**: deterministic UUID5 from absolute source path, not name/slug
- **Generator**: `random.Random(seed)`, seed=42 reproduces the blog-post corpus
- **init.py** uses the legacy `compile_wiki()` path (`.txt` only)
- **`wiki-cli` / `python -m src`** uses the full `Compiler` with SourceProvider (all 11 formats)
- **Linter** counts incoming links from every `##` section, not just `## Related`
- **Orphan check**: first tries store-backed RelationshipEngine, falls back to incoming link count
- **Duplicate titles**: index/readme/home/wiki_index pages exempt
- **No self-links**: entities never link to themselves in the graph
- **Cache invalidation**: `CURRENT_COMPILER_VERSION`, `CURRENT_EXTRACTOR_VERSION`, `CURRENT_TOKENIZER_VERSION` — bump any to force full rebuild

## License

MIT
