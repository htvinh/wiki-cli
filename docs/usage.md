# wiki-cli — Usage Guide

## Installation

### From source (development)

```bash
git clone https://github.com/Emmimal/wiki-cli.git
cd wiki-cli
pip install -e ".[dev]"
```

### With pipx (recommended for CLI-only use)

```bash
pipx install .
```

Or from the repo root after cloning:

```bash
pipx install /path/to/wiki-cli
```

### With pip

```bash
pip install .
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
| `output_dir` | Directory to write compiled .md pages into |

| Option | Default | Description |
|--------|---------|-------------|
| `--no-lint` | `false` | Skip the lint pass |
| `--watch, -w` | `false` | Watch for file changes and recompile automatically |
| `--poll-interval SEC` | `1.0` | Polling interval in seconds (used with `--watch`) |
| `--workers N` | `1` | Parallel extraction workers |

## Examples

```bash
# Basic compile
wiki-cli raw_notes/ compiled_wiki/

# Compile without validation
wiki-cli raw_notes/ compiled_wiki/ --no-lint

# Watch mode — recompiles on any change
wiki-cli raw_notes/ compiled_wiki/ --watch

# Faster polling interval in watch mode
wiki-cli raw_notes/ compiled_wiki/ --watch --poll-interval 0.5

# Parallel extraction (4 workers)
wiki-cli raw_notes/ compiled_wiki/ --workers 4
```

## Python API

```python
from src import Compiler, CompilerConfig

config = CompilerConfig(lint=True, workers=4)
compiler = Compiler(config=config)
result = compiler.compile("raw_notes", "compiled_wiki")

print(f"Compiled {result.pages_written} pages")
if result.lint_report:
    print(f"Broken links: {len(result.lint_report.broken_links)}")
    print(f"Orphan pages: {len(result.lint_report.orphan_pages)}")
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
    elif event.event == "done":
        print("Done!")
```

### Watch mode from Python

```python
import time
from src import Compiler, CompilerConfig

compiler = Compiler(CompilerConfig())
for event in compiler.watch("raw_notes", "compiled_wiki", poll_interval=1.0):
    if event.event == "watch_recompile":
        print("Change detected, recompiling...")
    elif event.event == "done":
        print(f"Recompiled at {time.strftime('%H:%M:%S')}")
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

## Output

Each entity is written as `<slug>.md` in the output directory:

```
# Entity Name

## Metadata
- created: 2024-01-01
- aliases: alt_name
- source: raw_notes/entity_name.txt

## Related
- [[Other Entity]]

## Referenced By
- [[Source Entity]]

## Body
(raw extracted body text)

## Notes
_(add your own notes here — preserved on recompile)_
```

The `## Notes` section is human-owned — any content you write there
survives recompilation.

## Tests

```bash
pip install -e ".[dev]"
python -m unittest src.tests -v
```
