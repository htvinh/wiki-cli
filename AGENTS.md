# wiki-cli — AGENTS.md

## Runtime: stdlib + markitdown. Dev: ruff + mypy (optional)
Runtime dep: `markitdown`. Python 3.12+. Dev deps via `pip install "wiki-cli[dev]"`.

## Commands
```bash
# CLI compile (direct or as module)
python src/compiler.py raw_notes/ compiled_wiki/
python -m src raw_notes/ compiled_wiki/
python src/compiler.py raw_notes/ compiled_wiki/ --no-lint

# Watch mode (recompile on file changes)
python src/compiler.py raw_notes/ compiled_wiki/ --watch

# Tests (stdlib unittest, 125 tests)
python -m unittest src.tests -v

# Benchmark
python src/benchmark.py --files 100 --files 1000

# Lint + typecheck (requires dev deps)
ruff check src/
mypy src/

# Zero-config demo
python src/init.py
```

## Package structure
```
wiki-cli/
├── pyproject.toml          # metadata, console_scripts, ruff/mypy config
└── src/
    ├── __init__.py         # pub API: Compiler, CompileEvent, Entity, ...
    ├── __main__.py         # python -m src
    ├── compiler.py         # Compiler class, CompilePlanner, ChangeDetector, CLI
    ├── converter.py        # MarkItDown document format conversion
    ├── exceptions.py       # WikiCompilerError hierarchy
    ├── extractor.py        # stage 1: regex entity extraction
    ├── generator.py        # deterministic synthetic corpus
    ├── graph.py            # stage 2: word-indexed mention matcher + GraphBuilder
    ├── init.py             # zero-config demo entrypoint
    ├── linter.py           # stage 4: broken-link + orphan validation
    ├── plugin.py           # Plugin, Extractor, Renderer, Validator, LinkResolver ABCs
    ├── rewriter.py         # stage 3: section-aware markdown output
    ├── source.py           # SourceProvider ABC + FilesystemProvider + ConvertingDocument
    ├── store.py            # Store ABC, SQLiteStore, MemoryStore, repos, migrations
    ├── watcher.py          # polling-based file watcher
    ├── benchmark.py        # timing harness
    └── tests.py            # 125 unittest tests
```

## Import convention
All modules use flat sibling imports (`from extractor import ...`).
`src/__init__.py` adds `src/` to `sys.path` so these resolve when
importing as a package. No `src.` prefix needed in internal imports.

## Pipeline (orchestrated by Compiler → CompilePlanner)
| Stage | File | Key detail |
|-------|------|------------|
| Converter | `converter.py` | MarkItDown: `.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`, `.csv`, `.json`, `.xml`, `.rtf` → markdown |
| Extractor | `extractor.py` | Reads `.txt`/`.md`/converted content. Header: `# Title` or bare UPPERCASE first line. Falls back to filename→Title. Raises `ExtractionError` on I/O failure. |
| Graph | `graph.py` | Word-indexed phrase matcher (not regex-per-entity). Lexical, not semantic. No self-links. Incremental via `WordIndexGraphBuilder`. |
| Rewriter | `rewriter.py` | Section-aware string replacement. `## Notes` is **preserved on recompile** (human-owned). Other sections fully regenerated. Raises `RewriteError` on I/O failure. |
| Linter | `linter.py` | Counts incoming links from `## Related` **only** (not `## Referenced By` — regression history). Broken links = `[[Name]]` not matching a `.md` slug. Raises `LintError` on I/O failure. |
| Watcher | `watcher.py` | Polling-based file watcher. Triggers incremental recompile on any file change. |

## Key quirks
- **Slug convention**: `_slugify(name)` = `name.lower().replace(" ", "_").replace("-", "_")`. Used for entity IDs, filenames, and link resolution everywhere.
- **Entity key**: `entity_id` (UUID5) is the dict key, not the display name or slug.
- **Generator**: deterministic via `random.Random(seed)`. `seed=42` reproduces the blog post corpus.
- **Init paths**: `init.py` resolves `raw_notes/` and `compiled_wiki/` relative to the project root (parent of `src/`), not CWD.
- **Error handling**: pipeline stages raise typed exceptions (`ExtractionError`, `RewriteError`, `LintError`) inheriting `WikiCompilerError`.
- **Logging**: modules use `logging.getLogger(__name__)`. Entry points configure level; `init.py` uses `WARNING` to keep output clean, `benchmark.py` also uses `WARNING`.
- **Multi-format input**: `FilesystemProvider` accepts `.txt`, `.md`, `.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`, `.csv`, `.json`, `.xml`, `.rtf`. Non-txt files auto-converted via MarkItDown.

## CI
`.github/workflows/ci.yml` runs tests on 3.12/3.13, plus `ruff check` and `mypy`.

## Edge cases already handled
- `.md` files in raw input are accepted (not ignored)
- Multi-word entity names matched via longest-first word-indexed strategy
- `## Notes` content survives recompile even when source body changes
- Orphan detection only examines `## Related` section links (not `## Referenced By`)
- HEADER_HASH_RE uses `\s+` (not `\s*`) to avoid matching `## Section` headers
- Vietnamese / mixed content tokenised correctly via `[\w']+` Unicode regex
