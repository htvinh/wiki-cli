# wiki-cli

A Python tool that compiles raw notes into a linked, linted markdown wiki. Deterministic, incremental, and supports multiple input formats via MarkItDown.

![Python Version](https://img.shields.io/badge/python-3.12%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## What It Does

```
Raw Notes (.txt, .md, .docx, .pdf, .html, ...)
  → MarkItDown conversion
  → Extractor (regex entity extraction)
  → Graph (word-indexed mention matching)
  → Rewriter (section-aware markdown output)
  → Linter (broken-link + orphan validation)
  → Compiled Wiki (.md)
```

## Features

- **Multi-format input**: `.txt`, `.md`, `.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`, `.csv`, `.json`, `.xml`, `.rtf` — automagically converted to markdown via MarkItDown
- **Deterministic**: same input → same output, every time. No LLM calls.
- **Incremental**: SHA-256 content hashing + mtime/size skip; only changed files are reprocessed
- **Watch mode**: `--watch` recompiles on any file change
- **Parallel extraction**: `--workers N` for multi-core speedup
- **Human-owned sections**: `## Notes` survives recompiles
- **Plugin system**: custom Extractors, Renderers, Validators, GraphBuilders, LinkResolvers
- **Persistent cache**: SQLite + filesystem body cache; survives full rebuilds
- **i18n**: Vietnamese and mixed content supported via Unicode `\w` tokeniser

## Installation

```bash
# Install from source (recommended)
git clone https://github.com/htvinh/wiki-cli.git
cd wiki-cli
pip install -e ".[dev]"

# Or install with pipx (CLI only)
pipx install .
```

## Quick Start

```bash
# Generate demo corpus
python src/init.py

# Compile raw notes → compiled wiki
wiki-cli raw_notes/ compiled_wiki/

# Watch for changes
wiki-cli raw_notes/ compiled_wiki/ --watch

# Parallel extraction (4 workers)
wiki-cli raw_notes/ compiled_wiki/ --workers 4
```

```python
from src import Compiler, CompilerConfig

config = CompilerConfig(lint=True)
compiler = Compiler(config=config)
result = compiler.compile("raw_notes", "compiled_wiki")

print(f"Compiled {result.pages_written} pages")
if result.lint_report:
    print(f"Broken links: {len(result.lint_report.broken_links)}")
    print(f"Orphan pages: {len(result.lint_report.orphan_pages)}")
```

## CLI Reference

```
wiki-cli raw_dir output_dir [options]

  raw_dir              Directory of raw source files
  output_dir           Directory to write compiled .md pages
  --no-lint            Skip the lint pass
  --watch, -w          Watch for file changes and recompile automatically
  --poll-interval SEC  Polling interval in seconds (default: 1.0)
  --workers N          Parallel extraction workers (default: 1)
```

## Tests

```bash
python -m unittest src.tests -v
```

125 tests across all stages: store, compiler pipeline, change detection, incremental graph, parallel extraction, plugins, watcher, source provider, converter.

## Benchmark

```bash
python src/benchmark.py --files 100 --files 1000 --files 5000
```

## Performance

| Files | Full pipeline |
|-------|--------------|
| 100   | ~170 ms      |
| 1,000 | ~1.8 s       |
| 5,000 | ~12 s        |

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

## License

MIT
