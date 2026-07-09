# wiki-cli — Usage Guide

## Installation

### From source (development)

```bash
git clone https://github.com/htvinh/wiki-cli.git
cd wiki-cli
pip install -e ".[dev]"
```

### With pipx (recommended for CLI-only use)

```bash
pipx install .
```

### Without install (ad-hoc)

```bash
python src/compiler.py raw_notes/ compiled_wiki/
python -m src raw_notes/ compiled_wiki/
```

## CLI Usage

```
wiki-cli raw_dir output_dir [options]
```

| Argument | Description |
|----------|-------------|
| `raw_dir` | Directory of raw source files (.txt, .md, .docx, .pdf, .html, .pptx, .xlsx, .csv, .json, .xml, .rtf) |
| `output_dir` | Directory to write compiled .md + .html pages into |

| Option | Default | Description |
|--------|---------|-------------|
| `--no-lint` | `false` | Skip the lint pass |
| `--strict` | `false` | Report optional metadata warnings (missing created/aliases) |
| `--workers N` | `1` | Parallel extraction workers |
| `--report` | `false` | Print graph report after compilation |

## Examples

```bash
# Basic compile
wiki-cli raw_notes/ compiled_wiki/

# Compile without validation
wiki-cli raw_notes/ compiled_wiki/ --no-lint

# Strict mode — report missing metadata
wiki-cli raw_notes/ compiled_wiki/ --strict

# Parallel extraction (4 workers)
wiki-cli raw_notes/ compiled_wiki/ --workers 4
```

## Output

### Compiled page format

Each entity is written as `<slug>.md` in the output directory:

```
# Entity Name

## Metadata
- created: 2024-01-01
- aliases: alt_name
- source: raw_notes/entity_name.txt

## Related
- [Other Entity](other_entity.md)
- (top-5 scored related pages)

## Linked From
- [Source Entity](source_entity.md)
- (all pages that link to this page)

## Body
(raw extracted body text)

## Notes
_(add your own notes here — preserved on recompile)_
```

The `## Notes` section is human-owned — any content you write there
survives recompilation.

### Index page

Each directory gets a generated `index.md` and `index.html` listing all
content pages:

```markdown
# Wiki Index

- [Entity Name](entity_name.md)
- [Other Entity](other_entity.md)
```

### Related page scoring

Pages in `## Related` are scored and ranked:

| Signal | Score |
|--------|-------|
| Same-folder sibling | +5 |
| Parent page | +3 |
| Lexical outgoing mention (`[[Page]]`) | +3 |
| Backlink (page that links to this) | +2 |
| Shared body words | +2 |
| Shared name words | +1 |

Top 5 results are displayed.

## CLI output

### Clean run

```
Compiled 20 content + 1 generated index page → 21 pages in 0.01s
Output: compiled_wiki/

Lint Summary
----------------------------
Pages checked:         21
Broken links:           0
Duplicate titles:       0
Unreachable pages:      0

✓ All checks passed.
```

### With warnings

```
Lint Summary
----------------------------
Pages checked:         42
Broken links:           0
Duplicate titles:       0
Unreachable pages:      13

Unreachable pages (13):
  • employee_handbook.md
  • benefits_guide.md

Status: PASS
```

### With errors

```
Lint Summary
----------------------------
Pages checked:         42
Broken links:           4
Duplicate titles:       1
Unreachable pages:       2

Errors
----------------------------
Broken links:
  page.md -> [Ghost Page] (target not found)

Duplicate titles:
  "My Title" in 2 content pages

Status: FAILED
```

## Python API

```python
from src import Compiler, CompilerConfig

config = CompilerConfig(lint=True, workers=4)
compiler = Compiler(config=config)
result = compiler.compile("raw_notes", "compiled_wiki")

print(f"Compiled {result.pages_written} pages in {result.stats.elapsed_s:.2f}s")
if result.lint_report:
    print(f"Broken links: {len(result.lint_report.broken_links)}")
```

### With store (persistent caching)

```python
from src import Compiler, CompilerConfig
from src import MemoryStore  # or SQLiteStore for persistence

store = MemoryStore()
compiler = Compiler(config=CompilerConfig(lint=True), store=store)
result = compiler.compile("raw_notes", "compiled_wiki")
```

### Event stream

```python
from src import Compiler, CompilerConfig

compiler = Compiler(CompilerConfig())
for event in compiler.compile_events("raw_notes", "compiled_wiki"):
    if event.event == "extracted":
        print(f"  Extracted: {event.entity_id}")
    elif event.event == "written":
        print(f"  Written: {event.entity_id}")
```

## Input Formats

| Format | Extensions | Notes |
|--------|------------|-------|
| Plain text | `.txt` | Read directly |
| Markdown | `.md` | Read directly |
| Word | `.docx` | Via MarkItDown |
| PDF | `.pdf` | Via MarkItDown |
| HTML | `.html`, `.htm` | Via MarkItDown |
| PowerPoint | `.pptx` | Via MarkItDown |
| Excel | `.xlsx` | Via MarkItDown |
| CSV | `.csv` | Via MarkItDown |
| JSON | `.json` | Via MarkItDown |
| XML | `.xml` | Via MarkItDown |
| Rich Text | `.rtf` | Via MarkItDown |

## Tests

```bash
pip install -e ".[dev]"
python -m unittest src.tests -v
```