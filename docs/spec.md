# wiki-cli — Specification & Design

## 1. Overview

wiki-cli is a pure-Python tool (stdlib + MarkItDown) that compiles a directory
of raw notes — `.txt`, `.md`, `.docx`, `.pdf`, `.html`, `.pptx`, `.xlsx`,
`.csv`, `.json`, `.xml`, `.rtf` — into a linked, linted markdown wiki. It
performs six sequential stages — conversion, extraction, graph construction,
rewriting, linting, and (optionally) persistent caching — all deterministically,
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
- **Self-validating**: the lint stage catches broken links and orphan pages
  before they accumulate.
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
  │          │            │          │            │
  └──────────┴────────────┴──────────┴────────────┘
                        │
  ┌──────────┬────────────┬──────────┬────────────┬──────────┐
  │          │            │          │            │          │
  Extractor GraphBuilder Renderer LinkResolver Validator
  │          │            │          │            │
  └──────────┴────────────┴──────────┴────────────┴──────────┘
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
     │                     │
     │     version cols stale? → re-extract
     │                     │
     │      hash → source_hash match? → skip
     │                     │
     ▼                     ▼
Extractor ──► EntityRepo ──► GraphBuilder ──► Renderer ──► Validator
     │           │               │               │              │
     │      body cache       word_index     .md files    LintReport
     │      (filesystem)     persistent       │
     │      aliases          edges            │
     └─────────────────────────────────────────┘
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
    ├── rewriter.py         # Stage 3: section-aware markdown output
    ├── source.py           # SourceProvider ABC + FilesystemProvider + ConvertingDocument
    ├── store.py            # Store ABC, SQLiteStore, MemoryStore, repos, migrations
    ├── watcher.py          # polling-based file watcher
    ├── benchmark.py        # timing harness
    └── tests.py            # 125 unittest tests
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
    PRIMARY KEY (source, target)
);

CREATE INDEX idx_graph_target ON graph_edges(target);

CREATE TABLE aliases (
    entity_id TEXT NOT NULL,
    alias     TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias)
);

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

### 3.5 Graph structure

Edges are stored in `graph_edges` table. For in-memory processing, the
graph is materialised as:

```python
{
    entity_id: {
        "outgoing": {target_id, ...},
        "incoming": {source_id, ...},
    },
    ...
}
```

### 3.6 LintReport

| Field | Type | Description |
|-------|------|-------------|
| `total_pages` | `int` | Number of `.md` files in output |
| `broken_links` | `list[tuple[str, str]]` | `(source_file, broken_target_name)` |
| `orphan_pages` | `list[str]` | Filenames with zero incoming links |

### 3.7 CompileResult + CompileStats

```python
@dataclass
class CompileResult:
    pages_written: int
    lint_report: LintReport | None
    stats: CompileStats

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
    orphans: int
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

Note: all collection-returning methods use iterators/streams rather than
materialising full dicts, to avoid memory explosion at scale.

class GraphRepo(ABC):
    def put_edge(self, source: str, target: str) -> None: ...
    def delete_outgoing(self, entity_id: str) -> None: ...
    def delete_incoming(self, entity_id: str) -> None: ...
    def get_outgoing(self, entity_id: str) -> set[str]: ...
    def get_incoming(self, entity_id: str) -> set[str]: ...
    def get_all_outgoing(self) -> dict[str, set[str]]: ...
    def get_edge_count(self) -> int: ...

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

### 4.2 Transaction context manager

Transactions are exposed via a context manager, not as raw `BEGIN`/`COMMIT`:

```python
class Store(ABC):
    @contextmanager
    def transaction(self) -> Generator[None, None, None]: ...
```

Each stage group is wrapped:

```python
with store.transaction():
    # ChangeDetector: update mtime/size/hashes

with store.transaction():
    # Extract: write entities + aliases

with store.transaction():
    # Graph: clear edges → scan → insert edges → update word_index

with store.transaction():
    # state.set("last_successful_stage", "render")
```

The context manager commits on success, rolls back on exception. If a stage
crashes, the cache is consistent up to the last committed transaction. The
next run picks up from the last successful stage.

### 4.3 Schema migration

A `Migration` interface handles version upgrades without dropping data:

```python
class Migration(ABC):
    @property
    def version(self) -> int: ...
    def migrate(self, conn: sqlite3.Connection) -> None: ...

MIGRATIONS = [Migration1(), Migration2(), ...]
```

On open, `SQLiteStore` reads `compile_state.schema_version`, applies any
pending migrations in order, and writes the new version.

### 4.4 SQLiteStore pragmas

Performance-critical settings applied on every connection:

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

### 5.2 API

```python
from converter import is_supported, needs_conversion, convert_to_text

# Check if a file extension is supported
is_supported("report.docx")  # True
is_supported("notes.xyz")    # False

# Check if conversion is needed (vs direct read)
needs_conversion("notes.txt")    # False (read directly)
needs_conversion("report.docx")  # True (convert via MarkItDown)

# Convert a document to markdown text
text = convert_to_text("report.docx")  # str
```

### 5.3 Integration

`FilesystemProvider.iter_documents()` returns `FilesystemDocument` for
`.txt`/`.md` files and `ConvertingDocument` for other formats.
`ConvertingDocument.read_bytes()` lazily calls `convert_to_text()` and
returns the UTF-8-encoded markdown. The extractor receives the converted
text via the `content` parameter:

```python
content = doc.read_bytes().decode("utf-8")
entity = extract_entity(doc.path, content=content)
```

### 5.4 Supported formats

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

Accepts document content (either read from a `.txt`/`.md` file or
pre-converted by MarkItDown) and extracts structured `Entity` objects.
The `FilesystemProvider` yields documents for `.txt`, `.md`, and any
MarkItDown-convertible format (`.docx`, `.pdf`, `.html`, etc.). Extraction
accepts an optional `content` parameter for pre-read text:

```python
def extract_entity(path: str, content: str | None = None) -> Entity: ...
```

### 6.2 Header detection

Two formats, checked in order:

1. **Hash header**: first non-empty line matching `^# (.+)$`.
2. **Bare uppercase header**: first non-empty line with zero lowercase letters
   (`line.isupper()`) at index 0 → converted via `.title()`. This heuristic
   is English-specific; Vietnamese and mixed-content files typically use the
   `#` format.

If neither matches, the name is derived from the filename:
`base.replace("_", " ").title()`.

### 6.3 Metadata extraction

After the header, each line is checked against:

- `^created:\s*(.+)$` (case-insensitive)
- `^aliases:\s*(.+)$` (case-insensitive) — split on commas

Both are optional. Matching lines are consumed; all others accumulate into
the body.

### 6.4 Change detection integration

Before extraction, `ChangeDetector` checks:
1. `mtime` + `size` from `os.stat()` against stored values → skip if match.
2. SHA-256 source hash against stored `source_hash` → skip extraction if
   match, reuse cached entity.
3. SHA-256 body hash against stored `body_hash` → skip recompile if match.
4. SHA-256 metadata hash against stored `metadata_hash` → skip graph update
   if match.

This means five `stat()` calls on steady state (no changes) and zero hashing
on steady state.

### 6.5 Edge cases

- Empty file → filename-derived title, empty body.
- File with only metadata → body is empty.
- Unknown metadata patterns → treated as body text.
- Vietnamese headers (`# Hệ Thống`) → extracted correctly via Unicode regex.
- Mixed English-Vietnamese body → extracted verbatim.

---

## 7. Stage 2: Graph

### 7.1 Purpose

Detects mentions of one entity's name inside another entity's body text and
builds a bidirectional reference map.

### 7.2 Word-indexed phrase matcher

Uses a word-indexed strategy to avoid O(n²):

1. **Index construction**: entity names are split into lowercase word-tuples.
   An index maps each first-word → `(word_tuple, entity_id)`, sorted
   longest-first for multi-word name priority.

2. **Scanning**: each body is tokenized once using `[\w']+` (Unicode-aware,
   supports Vietnamese). At each token position, the index is consulted for
   candidates; the longest matching tuple wins.

### 7.3 Key rules

- **No self-links**: mention of own name is ignored.
- **Case-insensitive**.
- **Whole-word**: `[\w']+` tokenisation; punctuation-spliced mentions are not
  matched.
- **Longest match wins**: "Attention Mechanism" beats "Attention" at the same
  position.

### 7.4 Incremental update

Driven by the `ChangeSet` (added, modified, deleted, renamed):

1. Remove all edges and index entries for deleted entities.
2. Delete outgoing edges for added/modified entities, then re-scan bodies.
3. For each added/modified entity's name words, query `word_index` for
   candidate pages → re-scan only those candidates.
4. Re-scan entities that previously linked to deleted entities (their
   `## Related` section must update).

At steady state: zero work for the graph stage.

### 7.5 i18n

Tokenisation uses `[\w']+`, where `\w` in Python 3 matches Unicode letters
including Vietnamese characters (`đ`, `ệ`, `ô`, `à`, `ả`, `ã`, etc.).
Vietnamese entity names like `Hệ Thống` are correctly tokenised and matched
in both Vietnamese and mixed-language bodies.

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
- [[Other Entity]]

## Referenced By
- [[Source Entity]]

## Body
(raw extracted body text)

## Notes
_(add your own notes here -- preserved on recompile)_
```

### 8.2 Section ownership

| Section | Ownership | Behaviour |
|---------|-----------|-----------|
| `## Metadata` | Compiler | Regenerated every compile |
| `## Related` | Compiler | Regenerated from graph edges |
| `## Referenced By` | Compiler | Regenerated from graph edges |
| `## Body` | Compiler | Regenerated from extracted body |
| `## Notes` | Human | Preserved verbatim across recompiles |

### 8.3 Notes preservation

Before writing, `render_page()` checks the output path. If a previous
`.md` file exists, it reads the old file, parses sections via `^## (.+)$`,
and preserves the `## Notes` section content. If no existing file, a
placeholder is written.

### 8.4 Incremental skip

If `body_hash` is unchanged and the entity is not in the changed set, the
page is skipped entirely (no I/O). The `## Notes` preservation still runs
(Notes can change independently of the source body), but the file is only
read, not written.

---

## 9. Stage 4: Linter (Validator)

### 8.1 Checks

1. **Broken links**: every `[[Link Name]]` in every output file is resolved
   via slug → known slugs. Unknown slugs are reported.
2. **Orphan pages**: pages with zero incoming links. Incoming links are
   counted from the `## Related` section only (not `## Referenced By`, which
   would double-count and produce false negatives).

### 8.2 LintReport

Returned by `lint()`. Formatted for human output via `print_report()`.

---

## 10. ChangeDetector

### 9.1 ChangeSet

Instead of a plain `set[str]` of changed IDs, ChangeDetector returns a typed
dataclass that captures every file lifecycle event:

```python
@dataclass
class ChangeSet:
    added: set[str]       # new files not in previous compile
    modified: set[str]    # existing files with changed content
    deleted: set[str]     # files removed from source
    renamed: dict[str, str]  # old_id → new_id (hash-based)
    unchanged: set[str]   # files with no changes (fast skip)
```

### 9.2 Algorithm

Before any hash check, version columns are verified. If any version column
is stale, the entity is re-extracted regardless of mtime/hash:

```
for each .txt file:
    stat() → (mtime, size)
    stored = store.entities.get(entity_id)

    if version columns stale (compiler, extractor, or tokenizer):
        force re-extract (cache is stale)

    elif stored and mtime == stored.mtime and size == stored.size:
        mark unchanged (no hash, no I/O)

    else:
        hash = sha256(file_content)
        if hash == stored.source_hash:
            update stored mtime/size only (body unchanged)

        else:
            extract entity
            if entity.body_hash == stored.body_hash:
                update source_hash + mtime/size + versions (page unchanged)
            elif entity.metadata_hash == stored.metadata_hash:
                mark graph for update, skip recompile
            else:
                mark full update needed

for each known entity_id not seen in this pass:
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

### 9.4 Rename detection

The `ChangeSet.renamed` map is populated via content hash comparison — if a
deleted file's hash matches an added file's hash, it's a rename rather than
a delete+add. This preserves incoming links across renames. Implementation is
deferred to a later phase; initial behaviour treats renames as delete+add.

### 9.5 Purpose

Determines which source files have changed since the last compile, using a
three-tier fast-skip strategy.

---

## 11. API Reference

### 10.1 Compiler class

The compiler accepts optional dependency injection — if no explicit
dependencies are provided, they are constructed from `CompilerConfig`:

```python
class Compiler:
    def __init__(
        self,
        config: CompilerConfig | None = None,
        planner: CompilePlanner | None = None,
        store: Store | None = None,
        source_provider: SourceProvider | None = None,
        graph_builder: GraphBuilder | None = None,
        link_resolver: LinkResolver | None = None,
    ): ...

    def compile(self, raw_dir: str, output_dir: str) -> CompileResult:
        """Blocking compile."""

    def compile_events(
        self, raw_dir: str, output_dir: str
    ) -> Generator[CompileEvent, None, CompileResult]:
        """Yields typed progress events, returns CompileResult."""
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
    watch: bool = False
    extractors: list[Extractor] | None = None
    renderers: list[Renderer] | None = None
    validators: list[Validator] | None = None
```

### 10.3 Progress events (CompileEvent)

```python
@dataclass
class CompileEvent:
    event: str         # phase_start, extracted, skipped, written, ...
    phase: str         # extract, graph, render, lint
    timestamp: float   # time.perf_counter()
    entity_id: str | None = None
    elapsed: float | None = None
    payload: dict | None = None
```

Standardised typed events instead of raw dicts. IDE-friendly, extensible.

### 10.4 Plugin interfaces

All plugins inherit from `PluginBase` for lifecycle management:

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

class StoreBackend(Plugin):
    def open(self, path: str) -> Store: ...
    def exists(self, path: str) -> bool: ...
    def delete(self, path: str) -> None: ...

@dataclass
class GraphBuilderResult:
    edge_count: int
    changed_edges: int
    orphans: int
    elapsed_s: float

class GraphBuilder(Plugin):
    def build(self, changes: ChangeSet, store: Store) -> GraphBuilderResult: ...

class LinkResolver(Plugin):
    def resolve(self, link_name: str, known_slugs: set[str]) -> str | None: ...
    def slugify(self, name: str) -> str: ...
```

`Compiler` calls `initialize()` on all plugins before the pipeline starts
and `shutdown()` after completion.

Default implementations: `TxtExtractor`, `MarkdownRenderer`, `WikiLinter`,
`WordIndexGraphBuilder`, `WikiLinkResolver`.

### 10.5 SourceProvider

Abstracts input sources so the compiler works with filesystem, archive,
Git repos, or remote sources without changes:

```python
class Document(ABC):
    @property
    def id(self) -> str: ...          # stable identifier (path, blob hash, etc.)
    @property
    def path(self) -> str: ...        # human-readable label
    @property
    def mtime(self) -> float: ...
    @property
    def size(self) -> int: ...
    def read_bytes(self) -> bytes: ...

class SourceProvider(ABC):
    def iter_documents(self, raw_dir: str) -> Generator[Document, None, None]: ...

class FilesystemProvider(SourceProvider):
    def iter_documents(self, raw_dir: str) -> Generator[Document, None, None]: ...
```

### 10.6 Plugin registration

```python
CompilerConfig(
    extractors=[TxtExtractor()],
    renderers=[MarkdownRenderer()],
    graph_builder=WordIndexGraphBuilder(),
    link_resolver=WikiLinkResolver(),
    store_backend=SQLiteStoreBackend(),
    source_provider=FilesystemProvider(),
)
```

---

## 12. CLI Reference

### 11.1 Main compiler

```
python src/compiler.py raw_dir output_dir [options]
python -m src raw_dir output_dir [options]
wiki-cli raw_dir output_dir [options]

Options:
  --no-lint             Skip the lint pass
  --watch, -w           Watch for file changes and recompile automatically
  --poll-interval SEC   Polling interval in seconds (default: 1.0)
  --workers N           Parallel extraction workers (default: 1)
```

### 11.2 Benchmark

```
python src/benchmark.py [--files N ...] [--seed N] [--workers N]
```

### 11.3 Init

```
python src/init.py
```

---

## 13. Exception Hierarchy

```
WikiCompilerError (Exception)
├── ExtractionError
├── RewriteError
├── LintError
└── StoreError        (persistence failures)
```

---

## 14. Testing

### 13.1 Test framework

Stdlib `unittest`. **125 tests** across 16 test classes covering every
stage, plugin, and integration point.

| Test class | Tests | Covers |
|------------|-------|--------|
| `TestGenerator` | 2 | Determinism, file count |
| `TestExtractor` | 8 | Hash/uppercase/filename header, aliases, `.md` acceptance, Vietnamese header, Vietnamese slug, mixed body, content param |
| `TestGraph` | 6 | Edge creation, self-link, orphan, Vietnamese mention, mixed mention, Vietnamese self-link |
| `TestRewriter` | 3 | Sections, notes preservation |
| `TestLinter` | 3 | Referenced-by regression, broken link, clean wiki |
| `TestFullPipeline` | 1 | End-to-end pipeline |
| `TestStore` | 17 | Entity round-trip, edge storage, word index, hash storage, `get_all_outgoing`, version columns |
| `TestStoreMigrations` | 3 | Migration framework |
| `TestCompiler` | 14 | Config, event stream, compile modes, DI, parallel output parity |
| `TestChangeDetector` | 7 | Version staleness, mtime/size fast skip, hash detection, deleted-file lifecycle |
| `TestCompilePlannerWithStore` | 6 | Planner + store integration |
| `TestGraphBuilder` | 4 | Incremental graph build, `WordIndexGraphBuilder` |
| `TestParallelExtraction` | 6 | Deterministic parallel output, worker count |
| `TestPlugin` | 8 | Plugin lifecycle, custom ABCs, default implementations |
| `TestWatcher` | 9 | File scan, change detection, initial compile, recompile on change |
| `TestSourceProvider` | 3 | Filesystem multi-format provider, document properties |
| `TestConverter` | 12 | Extension support checks, MarkItDown conversion |
| `TestExtractorWithContent` | 3 | Content-param extraction, file-fallback, filename-derived title |
| `TestSourceProviderMultiFormat` | 4 | Text, md, convertible, mixed formats |

### 13.2 Running

```bash
python -m unittest src.tests -v
```

---

## 15. CI Pipeline

`.github/workflows/ci.yml` on push/PR to `main`:

- **Test** (Python 3.12, 3.13): `python -m unittest src.tests -v`
- **Lint**: `ruff check src/`
- **Typecheck**: `mypy src/`

Dev deps: `ruff`, `mypy` (via `pip install "wiki-cli[dev]"`).

---

## 16. Performance Characteristics

Measured numbers stop at 10,000 files. Beyond that, figures are projected
targets — not claims — to guide architectural decisions.

| Files | Cold full pipeline | Incremental (no changes) | Incremental (1 file edited) |
|-------|-------------------|-------------------------|-----------------------------|
| 100 | ~15 ms | ~2 ms | ~2 ms |
| 1,000 | ~1.8 s | ~10 ms | ~15 ms |
| 5,000 | ~12 s | ~50 ms | ~50 ms |
| 10,000 | ~30 s (target) | ~100 ms (target) | ~100 ms (target) |
| 100,000 | ~4 min (projected) | ~1 s (projected) | ~2 s (projected) |
| 1,000,000 | ~40 min (projected) | ~10 s (projected) | ~30 s (projected) |

Projections assume SQLite WAL mode, mtime-based skip on steady state, and
proportional cost per changed entity for incremental builds.

Key observations:
- **Steady state**: cost is `O(n)` `stat()` calls with zero hashing.
- **Incremental (one file)**: cost is proportional to the changed file plus
  its mention candidates, not total corpus size.
- **Parallel extraction**: 3-5× speedup on extraction for 1000+ files
  (using `concurrent.futures.ProcessPoolExecutor` with `executor.map()`
  for deterministic submission order).
- **Lint**: after Phase 1, orphan counts come from the Store instead of
  re-reading `.md` files, eliminating the I/O bottleneck.

---

## 17. Known Limitations

1. **Lexical mention detection**: exact word matching, not semantic.
2. **Limited header formats**: two styles (`#` and bare uppercase).
   Files with `##`, `===`, etc. fall back to filename-derived names.
3. **Single-file metadata**: `created` and `aliases` must appear between
   header and body. Interleaved metadata is not recognised.
4. **No cycle detection**: circular reference chains are allowed.
5. **Slug-based link resolution**: renaming a display name changes the slug
   and breaks incoming `[[links]]`. The linter detects this; no automatic
   fixup is performed.
6. **Rename detection**: source file renames are currently handled as
   delete+add. Hash-based rename detection is deferred to a later phase.

---

## 18. Edge Cases Handled

- `.md` files in raw input are accepted and processed like `.txt` files.
- Empty raw directory → empty output with zero-page lint report.
- All I/O uses UTF-8 explicitly.
- Multi-word entity names use longest-first matching.
- `## Notes` survives recompilation across source changes.
- Orphan detection only counts `## Related` (not `## Referenced By`).
- Vietnamese + mixed content tokenised correctly via `[\w']+`.
- UUID5 entity IDs survive display name renames (only slug changes).
- Content hashing detects body-only, metadata-only, and combined changes.
- SQLite WAL mode supports concurrent reads during parallel extraction.
- Three-tier skip (mtime → source_hash → body_hash) minimises I/O on
  steady state.
