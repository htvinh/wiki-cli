# wiki-cli — Specification & Design

## 1. Overview

wiki-cli is a pure-Python tool (stdlib + MarkItDown) that compiles a directory
of raw notes — `.txt`, `.md`, `.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`,
`.csv`, `.json`, `.xml`, `.rtf` — into a linked, linted markdown wiki. It
performs four sequential stages — extraction, graph construction (three-graph:
navigation, link, folder), rewriting, and linting — all deterministically,
without any LLM calls, embeddings, or external services.

Designed to scale from hundreds to millions of documents via incremental
compilation, content hashing, streaming, and parallel extraction.

**Target Python**: 3.12+ (dependencies: `markitdown`).
**License**: MIT.

### 1.1 Design goals

- **Deterministic**: given the same input, always produce the same output.
  No randomness, no model calls, no network I/O during compilation.
- **Minimal runtime dependencies**: `markitdown` for multi-format document
  conversion; everything else is Python standard library (including `sqlite3`
  for persistent storage).
- **Human-in-the-loop**: the `## Notes` section of each compiled page is
  preserved across recompiles, so hand-written annotations survive source
  changes.
- **Incremental by default**: unchanged files are detected via mtime/size
  and content hashing; only changed pages are re-extracted, re-graphed,
  and re-rendered.
- **Self-validating**: the lint stage catches broken links, duplicate titles,
  and unreachable pages before they accumulate.
- **i18n**: English, Vietnamese, and mixed content fully supported. The
  tokeniser uses Unicode word boundaries (`\w`), not ASCII-only patterns.
- **Multi-format input**: MarkItDown converts `.docx`, `.pdf`, `.html`,
  `.pptx`, `.xlsx`, `.csv`, `.json`, `.xml`, `.rtf` to markdown on the fly;
  `.txt` and `.md` files are read directly.
- **Watch mode**: polling-based file watcher (`--watch`) triggers incremental
  recompile on any source file change.

---

## 2. Architecture

### 2.1 System diagram

```
                    Compiler (thin orchestrator)
                        │
                   CompilePlanner
                        │
                 ChangeDetector
                        │
                SourceProvider
                        │
                     Store (facade)
                        │
  ┌──────────┬────────────┬──────────┬────────────┐
  │          │            │          │            │
  Entity   GraphRepo  IndexRepo  StateRepo  ContentRepo
  └──────────┴────────────┴──────────┴────────────┘
                        │
  ┌──────────┬────────────┬──────────┬────────────┐
  │          │            │          │            │
  Extractor GraphBuilder Renderer   LinkResolver  Validator
  └──────────┴────────────┴──────────┴────────────┘
                        │
                   CompileStats
                        │
                   Event Stream
```

Each component has a single responsibility. The `Compiler` is a thin
orchestrator that delegates to `CompilePlanner`. The planner runs
`ChangeDetector`, then invokes extractors, graph builder, renderer, and
validator — all via the `Store` abstraction. `SourceProvider` abstracts
input sources (filesystem, archive, remote). `LinkResolver` isolates wiki
link logic from the core pipeline.

### 2.2 Pipeline flow

```
Raw Notes (.txt, .md, .docx, .pdf, .html, ...)
     │
     ▼
Converter (MarkItDown) ──► markdown text
     │
     ▼
ChangeDetector: stat → mtime/size match? → skip
     │                    │
     │    version cols stale? → re-extract
     │                    │
     │    hash → source_hash match? → skip
     │                    │
     ▼                    ▼
Extractor ──► EntityRepo ──► GraphBuilder ──► Renderer ──► Validator
     │           │               │               │              │
     │      body cache     3-graph       .md + .html    LintReport
     │      (filesystem)    builder         files
     │      aliases         (nav/link/
     └────────────────────  folder)─────────────────────────────┘
                                        Watch Mode
                                     (polling loop)
```

### 2.3 Package structure

```
wiki-cli/
├── pyproject.toml          # metadata, console_scripts, ruff/mypy config
├── README.md
├── AGENTS.md
├── .gitignore
├── .github/workflows/ci.yml
└── src/
    ├── __init__.py         # pub API: Compiler, CompileEvent, Entity, ...
    ├── __main__.py         # python -m src
    ├── compiler.py         # Compiler class, CompilePlanner, ChangeDetector, CLI
    ├── converter.py        # MarkItDown document format conversion
    ├── exceptions.py       # WikiCompilerError hierarchy
    ├── extractor.py        # Stage 1: regex entity extraction
    ├── generator.py        # deterministic synthetic corpus
    ├── graph.py            # Stage 2: word-indexed mention matcher + GraphBuilder
    ├── init.py             # zero-config demo entrypoint
    ├── linter.py           # Stage 4: broken-link + orphan validation
    ├── plugin.py           # Plugin, Extractor, Renderer, Validator, LinkResolver ABCs
    ├── relationship.py     # Three-graph engine (nav, link, folder)
    ├── rewriter.py         # Stage 3: section-aware markdown + HTML output
    ├── source.py           # SourceProvider ABC + FilesystemProvider + ConvertingDocument
    ├── store.py            # Store ABC, SQLiteStore, MemoryStore, repos, migrations
    ├── watcher.py          # polling-based file watcher
    ├── benchmark.py        # timing harness
    └── tests.py            # 136 unittest tests
```

### 2.4 Import convention

All modules use flat sibling imports (`from extractor import ...`). The file
`src/__init__.py` adds `src/` to `sys.path` so these resolve both when
running directly and when importing as a package.

---

## 3. Data Model

### 3.1 Entity

Defined as a dataclass in `extractor.py`:

| Field | Type | Description |
|-------|------|-------------|
| `entity_id` | `str` | UUID5 (deterministic from source path) |
| `name` | `str` | Display name |
| `slug` | `str` | Derived from name, used for filenames and link resolution |
| `aliases` | `list[str]` | Alternate names for mention matching |
| `created` | `str` | Optional creation date (free text) |
| `body` | `str` | Raw extracted body text |
| `source_path` | `str` | Path to the original `.txt` file |

Entity IDs are deterministic UUID5 derived from the source path — same path
always produces the same ID. The slug (derived from display name) is separate;
renaming a title updates the slug but the UUID stays the same. Cache survives
full rebuilds.

```python
import uuid
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://wiki-cli/entities")

def make_entity_id(source_path: str) -> str:
    return uuid.uuid5(_NAMESPACE, source_path).hex  # 32 hex chars
```

### 3.2 Slug convention

```
_slugify(name) = name.lower().replace(" ", "_").replace("-", "_")
```

Slugs are used for output filenames (`<slug>.md`) and `[[Display Name]]` link
resolution. The slug may change on rename (caught by the linter), but the UUID
entity ID never changes.

### 3.3 Persistence: SQLiteStore schema

Bodies are stored on the filesystem under `<cache_dir>/bodies/<uuid>.txt`,
not in SQLite. The SQLite database stores metadata, graph edges, hashes,
indexes, and state.

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA cache_size=-64000;
PRAGMA foreign_keys=ON;

CREATE TABLE compile_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE entities (
    id                TEXT PRIMARY KEY,
    slug              TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    aliases           TEXT DEFAULT '',
    created           TEXT DEFAULT '',
    source_path       TEXT DEFAULT '',
    source_hash       TEXT DEFAULT '',
    body_hash         TEXT DEFAULT '',
    metadata_hash     TEXT DEFAULT '',
    mtime             REAL DEFAULT 0,
    size              INTEGER DEFAULT 0,

    -- version tracking for cache invalidation
    compiler_version  TEXT DEFAULT '',
    extractor_version TEXT DEFAULT '',
    tokenizer_version TEXT DEFAULT ''
);

CREATE TABLE graph_edges (
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    graph_name TEXT NOT NULL DEFAULT 'lexical',
    edge_type TEXT DEFAULT '',
    PRIMARY KEY (source, target, graph_name)
);

CREATE INDEX idx_graph_target ON graph_edges(target);

CREATE TABLE word_index (
    word               TEXT NOT NULL,
    entity_id          TEXT NOT NULL,
    frequency          INTEGER DEFAULT 1,
    document_frequency INTEGER DEFAULT 1,
    PRIMARY KEY (word, entity_id)
);

CREATE INDEX idx_word ON word_index(word);
```

The store lives at `<cache_dir>/wiki.db` and is gitignored. Deleting it
forces a full rebuild with identical output.

### 3.4 CompileState keys

| Key | Purpose |
|-----|---------|
| `schema_version` | Migrate DB schema between compiler versions |
| `compiler_version` | Detect stale cache from a different version |
| `last_compile` | Timestamp for diagnostics |
| `last_successful_compile` | Resume support |
| `entity_count` | Quick stats without counting rows |
| `edge_count` | Quick stats without counting rows |

### 3.5 Graph structure (three-graph)

Edges are stored in `graph_edges` with a `graph_name` column distinguishing
three graphs: `navigation` (folder hierarchy), `lexical` (`[[Page]]` mentions),
and `folder` (parent/child/sibling). Each graph is independently queryable:

```python
store.graph.get_outgoing(entity_id, "lexical")      # [[Page]] mentions
store.graph.get_outgoing(entity_id, "navigation")    # parent/child
store.graph.get_outgoing(entity_id, "folder")        # folder siblings
```

### 3.6 LintReport

| Field | Type | Description |
|-------|------|-------------|
| `total_pages` | `int` | Number of `.md` files in output |
| `content_pages` | `int` | Content pages (not index/README/Home) |
| `index_pages` | `int` | Generated index pages |
| `broken_links` | `list[tuple[str, str]]` | `(source_file, broken_target_name)` |
| `duplicate_titles` | `list[tuple[str, list[str]]]` | `(title, [filenames])` for content pages only |
| `unreachable_pages` | `list[str]` | Pages with no parent, no child, no backlinks, no index reference |
| `missing_metadata` | `list[tuple[str, str]]` | `(filename, field)` — only shown in `--strict` mode |

### 3.7 Lint checks

1. **Broken links**: every `[name](slug.md)` is resolved to a known slug.
   Unknown slugs are reported.
2. **Duplicate titles**: content pages only. Index pages (`index.md`,
   `home.md`, `readme.md`, "Wiki Index") are exempt.
3. **Unreachable pages**: a page is unreachable if it has no parent
   (navigation), no child (navigation), no backlink (`[[Page]]` from
   another page), and is not referenced by any index page.
4. **Missing metadata** (optional, `--strict` only): `created` and
   `aliases` fields.

### 3.8 CompileResult + CompileStats

```python
@dataclass
class CompileResult:
    pages_written: int
    lint_report: LintReport | None
    stats: CompileStats
    graph_report: GraphReport | None = None

@dataclass
class CompileStats:
    entity_count: int
    edge_count: int
    pages_changed: int
    pages_skipped: int
    added: int
    deleted: int
    renamed: int
    cache_hits: int
    cache_misses: int
    cache_hit_ratio: float
    broken_links: int
    lexical_unlinked: int
    elapsed_s: float
    entities_per_sec: float
    pages_per_sec: float
    graph_time_s: float
    hash_time_s: float
    sqlite_time_s: float
    io_time_s: float
    peak_memory_mb: float
    sqlite_size_kb: int
    body_cache_size_kb: int
```

---

## 4. Store (Persistence Layer)

### 4.1 Interface

`Store` is an abstract base class that acts as a facade over four independent
repositories. Each repository has a focused interface and can be replaced
independently. The initial implementation is `SQLiteStore`; a `MemoryStore`
is available for testing.

```python
class EntityRepo(ABC):
    def put(self, entity: Entity) -> None: ...
    def get(self, entity_id: str) -> Entity | None: ...
    def iter_entities(self) -> Generator[Entity, None, None]: ...
    def iter_ids(self) -> Generator[str, None, None]: ...
    def iter_changed(self, changed_ids: set[str]) -> Generator[Entity, None, None]: ...
    def iter_by_slug(self, slug: str) -> Entity | None: ...
    def exists(self, entity_id: str) -> bool: ...
    def delete(self, entity_id: str) -> None: ...

class GraphRepo(ABC):
    def put_edge(self, source: str, target: str, graph_name: str = "lexical", edge_type: str = "") -> None: ...
    def delete_outgoing(self, entity_id: str, graph_name: str | None = None) -> None: ...
    def delete_incoming(self, entity_id: str, graph_name: str | None = None) -> None: ...
    def get_outgoing(self, entity_id: str, graph_name: str | None = None) -> set[str]: ...
    def get_incoming(self, entity_id: str, graph_name: str | None = None) -> set[str]: ...
    def get_edge_type(self, source: str, target: str, graph_name: str) -> str | None: ...
    def get_all_outgoing(self, graph_name: str | None = None) -> dict[str, set[str]]: ...
    def get_edge_count(self, graph_name: str | None = None) -> int: ...
    def get_graph_names(self) -> set[str]: ...

class IndexRepo(ABC):
    def index_name(self, entity_id: str, name: str) -> None: ...
    def drop_entity_index(self, entity_id: str) -> None: ...
    def get_candidates(self, word: str) -> list[str]: ...

class StateRepo(ABC):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def get_int(self, key: str) -> int | None: ...
    def get_float(self, key: str) -> float | None: ...

class ContentRepository(ABC):
    def put(self, entity_id: str, body: str) -> None: ...
    def get(self, entity_id: str) -> str | None: ...
    def delete(self, entity_id: str) -> None: ...
    def size(self) -> int: ...

class Store(ABC):
    @property
    def entities(self) -> EntityRepo: ...
    @property
    def graph(self) -> GraphRepo: ...
    @property
    def index(self) -> IndexRepo: ...
    @property
    def state(self) -> StateRepo: ...
    @property
    def content(self) -> ContentRepository: ...
    @contextmanager
    def transaction(self) -> Generator[None, None, None]: ...
    def close(self) -> None: ...
    def vacuum(self) -> None: ...
```

### 4.2 Graph names

Three named graphs in `graph_edges`:

| `graph_name` | Contents |
|-------------|----------|
| `navigation` | Folder hierarchy: parent → child edges from `RelationshipEngine.build_all()` |
| `lexical` | `[[Page]]` mention links from `WordIndexGraphBuilder` |
| `folder` | Parent/child/sibling edges used for `compute_related()` scoring |

### 4.3 Transaction context manager

Each stage group is wrapped:

```python
with store.transaction():
    # ChangeDetector: update mtime/size/hashes

with store.transaction():
    # Extract: write entities

with store.transaction():
    # Graph: clear edges → scan → insert edges → update word_index

with store.transaction():
    # relationship: build navigation edges
```

### 4.4 Schema migration

A `Migration` interface handles version upgrades without dropping data.

```python
class Migration(ABC):
    @property
    def version(self) -> int: ...
    def migrate(self, conn: sqlite3.Connection) -> None: ...
```

On open, `SQLiteStore` reads `compile_state.schema_version`, applies any
pending migrations in order, and writes the new version.

### 4.5 SQLiteStore pragmas

| Pragma | Value | Effect |
|--------|-------|--------|
| `journal_mode` | `WAL` | Concurrent reads during writes |
| `synchronous` | `NORMAL` | Balance durability vs write speed |
| `temp_store` | `MEMORY` | Avoid temp file I/O |
| `cache_size` | `-64000` | 64 MB page cache |

---

## 5. Converter (Preprocessing)

### 5.1 Purpose

Converts non-plaintext documents (`.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`,
`.csv`, `.json`, `.xml`, `.rtf`) to markdown text so they flow through the
wiki pipeline like native `.txt` files. Implemented in `src/converter.py`
using MarkItDown.

### 5.2 Supported formats

| Extension | Format | Notes |
|-----------|--------|-------|
| `.txt` | Plain text | Direct read |
| `.md` | Markdown | Direct read |
| `.docx` | Word document | Via MarkItDown |
| `.pdf` | PDF | Via MarkItDown |
| `.html` / `.htm` | HTML | Via MarkItDown |
| `.pptx` | PowerPoint | Via MarkItDown |
| `.xlsx` | Excel | Via MarkItDown |
| `.csv` | CSV | Via MarkItDown |
| `.json` | JSON | Via MarkItDown |
| `.xml` | XML | Via MarkItDown |
| `.rtf` | Rich Text Format | Via MarkItDown |

---

## 6. Stage 1: Extractor

### 6.1 Purpose

Accepts document content and extracts structured `Entity` objects.

### 6.2 Header detection

1. **Hash header**: first non-empty line matching `^# (.+)$`.
2. **Bare uppercase header**: first non-empty line with zero lowercase letters
   (`line.isupper()`) at index 0 → converted via `.title()`.

If neither matches, the name is derived from the filename:
`base.replace("_", " ").title()`.

### 6.3 Metadata extraction

After the header, each line is checked against:

- `^created:\s*(.+)$` (case-insensitive)
- `^aliases:\s*(.+)$` (case-insensitive) — split on commas

Both are optional. Matching lines are consumed; all others accumulate into
the body.

### 6.4 Edge cases

- Empty file → filename-derived title, empty body.
- File with only metadata → body is empty.
- Vietnamese headers (`# Hệ Thống`) → extracted correctly via Unicode regex.

---

## 7. Stage 2: Graph

### 7.1 Word-indexed phrase matcher

Uses a word-indexed strategy to avoid O(n²):

1. **Index construction**: entity names are split into lowercase word-tuples.
   An index maps each first-word → `(word_tuple, entity_id)`, sorted
   longest-first for multi-word name priority.
2. **Scanning**: each body is tokenized once using `[\w']+` (Unicode-aware,
   supports Vietnamese). At each token position, the index is consulted for
   candidates; the longest matching tuple wins.

### 7.2 Key rules

- **No self-links**: mention of own name is ignored.
- **Case-insensitive**.
- **Whole-word**: `[\w']+` tokenisation.
- **Longest match wins**: "Attention Mechanism" beats "Attention".

### 7.3 Incremental update

Driven by the `ChangeSet` (added, modified, deleted):

1. Remove all edges and index entries for deleted entities.
2. Delete outgoing edges for added/modified entities, then re-scan bodies.
3. For each added/modified entity's name words, query `word_index` for
   candidate pages → re-scan only those candidates.

At steady state: zero work for the graph stage.

---

## 8. Stage 3: Rewriter

### 8.1 Output page format

```
# Display Name

## Metadata
- created: 2026-01-01
- aliases: foo, foo_notes
- source: raw_notes/<slug>.txt

## Related
- [Other Entity](other_entity.md)

## Linked From
- [Source Entity](source_entity.md)

## Body
(raw extracted body text)

## Notes
_(add your own notes here -- preserved on recompile)_
```

### 8.2 Section ownership

| Section | Ownership | Behaviour |
|---------|-----------|-----------|
| `## Metadata` | Compiler | Regenerated every compile |
| `## Related` | Compiler | Top-5 scored from navigation + lexical + folder graphs |
| `## Linked From` | Compiler | All pages that link to this page |
| `## Body` | Compiler | Regenerated from extracted body |
| `## Notes` | Human | Preserved verbatim across recompiles |

### 8.3 Related page scoring

The `RelationshipEngine.compute_related()` produces a ranked list:

| Signal | Score |
|--------|-------|
| Same-folder sibling | +5 |
| Parent page | +3 |
| Lexical outgoing mention (`[[Page]]`) | +3 |
| Backlink (page that links to this) | +2 |
| Shared body words (every 5 tokens) | +2 |
| Shared name words | +1 |

Top 5 are written to `## Related`.

### 8.4 Index page generation

For each directory in the output, an `index.md` and `index.html` are generated
automatically, listing all `.md` files and subdirectories.

### 8.5 Notes preservation

Before writing, `render_page()` checks the output path. If a previous
`.md` file exists, it reads the old file, parses sections via `^## (.+)$`,
and preserves the `## Notes` section content. If no existing file, a
placeholder is written.

---

## 9. ChangeDetector

### 9.1 ChangeSet

```python
@dataclass
class ChangeSet:
    added: set[str]       # new files not in previous compile
    modified: set[str]       # existing files with changed content
    deleted: set[str]     # files removed from source
    renamed: dict[str, str]  # old_id → new_id (hash-based)
    unchanged: set[str]   # files with no changes (fast skip)
```

### 9.2 Algorithm

```
for each file:
    stat() → (mtime, size)

    if version columns stale (compiler, extractor, tokenizer):
        force re-extract
    elif stored and mtime == stored.mtime and size == stored.size:
        mark unchanged
    else:
        hash = sha256(file_content)
        if hash == stored.source_hash:
            update stored mtime/size only
        else:
            extract entity
            if entity.body_hash == stored.body_hash:
                update source_hash + mtime/size + versions
            else:
                mark full update

for each stored entity not seen:
    mark deleted
```

### 9.3 Deleted-document lifecycle

When a source file is removed:

1. `ChangeDetector` adds its ID to `ChangeSet.deleted`.
2. `CompilePlanner` calls `store.entities.delete(id)` → removes from DB.
3. `store.graph.delete_outgoing(id)` → removes all edges.
4. `store.graph.delete_incoming(id)` → removes inbound edges.
5. `store.index.drop_entity_index(id)` → removes from word index.
6. `store.content.delete(id)` → removes content cache file.
7. `os.remove(output_file)` → removes rendered `.md`.
8. All dependent pages are re-rendered (their `## Related` section changes).

---

## 10. API Reference

### 10.1 Compiler class

```python
class Compiler:
    def __init__(
        self,
        config: CompilerConfig | None = None,
        planner: CompilePlanner | None = None,
        store: Store | None = None,
        source_provider: SourceProvider | None = None,
        graph_builder: GraphBuilder | None = None,
    ): ...

    def compile(self, raw_dir: str, output_dir: str) -> CompileResult: ...

    def compile_events(
        self, raw_dir: str, output_dir: str
    ) -> Generator[CompileEvent, None, CompileResult]: ...
```

### 10.2 CompilerConfig

```python
@dataclass
class CompilerConfig:
    cache_dir: str = ".cache"
    workers: int = 1
    lint: bool = True
    incremental: bool = True
    parallel: bool = False
    strict: bool = False
    navigation_hubs: int = 0
    source_provider: SourceProvider | None = None
    extractors: list | None = None
    renderers: list | None = None
    validators: list | None = None
    link_resolver: object | None = None
```

### 10.3 Plugin interfaces

All plugins inherit from `Plugin` for lifecycle management:

```python
class Plugin(ABC):
    def initialize(self, config: CompilerConfig) -> None: ...
    def shutdown(self) -> None: ...

class Extractor(Plugin):
    def can_handle(self, path: str) -> bool: ...
    def extract(self, path: str, store: Store) -> Entity: ...

class Renderer(Plugin):
    def render(self, entity: Entity, outgoing: set[str], incoming: set[str], store: Store) -> str: ...

class Validator(Plugin):
    def validate(self, output_dir: str, store: Store) -> LintReport: ...

class GraphBuilder(Plugin):
    def build(self, changes: ChangeSet, store: Store, entities: dict[str, Entity]) -> GraphBuilderResult: ...

class LinkResolver(Plugin):
    def resolve(self, link_name: str, known_slugs: set[str]) -> str | None: ...
    def slugify(self, name: str) -> str: ...
```

Default implementations: `TxtExtractor`, `MarkdownRenderer`, `WikiLinter`,
`WordIndexGraphBuilder`, `WikiLinkResolver`.

---

## 11. CLI Reference

### 11.1 Main compiler

```
python src/compiler.py raw_dir output_dir [options]
python -m src raw_dir output_dir [options]
wiki-cli raw_dir output_dir [options]

Options:
  --no-lint             Skip the lint pass
  --strict              Report optional metadata warnings (missing created/aliases)
  --workers N           Parallel extraction workers (default: 1)
  --report              Print graph report after compilation
```

### 11.2 Output example

```
....................
Compiled 20 content + 1 generated index page → 21 pages in 0.01s
Output: /tmp/wiki_ux

Lint Summary
----------------------------
Pages checked:         21
Broken links:           0
Duplicate titles:       0
Unreachable pages:      0

✓ All checks passed.
```

### 11.3 Benchmark

```
python src/benchmark.py [--files N ...] [--seed N] [--workers N]
```

### 11.4 Init

```
python src/init.py
```

---

## 12. Exception Hierarchy

```
WikiCompilerError (Exception)
├── ExtractionError
├── RewriteError
├── LintError
└── StoreError
```

---

## 13. Testing

**136 tests** across 16 test classes covering every
stage, plugin, and integration point.

| Test class | Tests | Covers |
|------------|-------|--------|
| `TestGenerator` | 2 | Determinism, file count |
| `TestExtractor` | 8 | Hash/uppercase/filename header, aliases, `.md` acceptance, Vietnamese |
| `TestGraph` | 6 | Edge creation, self-link, orphan, Vietnamese mention |
| `TestRewriter` | 3 | Sections, notes preservation |
| `TestLinter` | 3 | Unreachable detection, broken link, clean wiki |
| `TestFullPipeline` | 2 | End-to-end idempotency |
| `TestStore` | 17 | Entity round-trip, edge storage, version columns |
| `TestStoreMigrations` | 3 | Migration framework |
| `TestCompiler` | 14 | Config, event stream, compile modes, DI |
| `TestChangeDetector` | 7 | Version staleness, mtime/size, hash, deleted |
| `TestCompilePlannerWithStore` | 6 | Planner + store integration |
| `TestGraphBuilder` | 4 | Incremental graph build with store |
| `TestParallelExtraction` | 6 | Deterministic parallel output |
| `TestPlugin` | 8 | Plugin lifecycle, ABCs, defaults |
| `TestWatcher` | 9 | File scan, initial compile, recompile |
| `TestSourceProvider` | 3 | Multi-format provider, doc properties |
| `TestConverter` | 12 | Extension support, MarkItDown conversion |

```bash
python -m unittest src.tests -v
```

---

## 14. CI Pipeline

`.github/workflows/ci.yml` on push/PR to `main`:

- **Test** (Python 3.12, 3.13): `python -m unittest src.tests -v`
- **Lint**: `ruff check src/`
- **Typecheck**: `mypy src/`

Dev deps: `ruff`, `mypy` (via `pip install "wiki-cli[dev]"`).

---

## 15. Known Limitations

1. **Lexical mention detection**: exact word matching, not semantic.
2. **Limited header formats**: two styles (`#` and bare uppercase).
   Files with `##`, `===`, etc. fall back to filename-derived names.
3. **No cycle detection**: circular reference chains are allowed.
4. **Slug-based link resolution**: renaming a display name changes the slug
   and breaks incoming `[[links]]`. The linter detects this; no automatic
   fixup is performed.
5. **Rename detection**: source file renames are currently handled as
   delete+add. Hash-based rename detection is deferred.