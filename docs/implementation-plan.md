# Implementation Plan — Complete

All 7 phases have been implemented. Summary below.

## Architecture

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
 Converter Extractor GraphBuilder Renderer LinkResolver Validator
  └──────────┴────────────┴──────────┴────────────┘
                        │
                   CompileStats
                        │
                   Event Stream
```

Each component has a single responsibility. `SourceProvider` abstracts
input sources (filesystem, archive, remote). The `Converter` uses MarkItDown
to translate non-txt documents to markdown. `LinkResolver` isolates wiki
link logic from the core pipeline.

---

## Phase 0 — Unicode Tokenisation ✅

**Change**: `graph.py:13` — `_WORD_RE` from `[A-Za-z0-9']+` → `[\w']+`.

Python 3's `\w` matches Unicode letters (Vietnamese `đ`, `ệ`, `ô`, `à`, `ả`,
`ã`, etc.), not just ASCII. All other stages (`_slugify` via `.lower()`, regex
header detection, filename fallback) already handle Unicode correctly.

**Tests**: 6 new (23 total at this stage).

---

## Phase 1 — Store + Persistence Layer ✅

**Design**: bodies on filesystem (`<cache>/bodies/<uuid>.txt`), SQLite for
metadata/graph/hashes/state. Store split into 5 repos (Entity, Graph, Index,
State, Content) behind a facade ABC.

**Implementations**: `SQLiteStore` (WAL, schema v1, migration framework) and
`MemoryStore` (testing). Transaction context manager with commit-on-success /
rollback-on-exception.

**Files**: `src/store.py` — Store, EntityRepo, GraphRepo, IndexRepo, StateRepo,
ContentRepository, SQLiteStore, MemoryStore, make_entity_id, Migration ABC.

**Tests**: 17 Store tests + 3 migration tests.

---

## Phase 1.5 — Deterministic Stable IDs ✅

**Change**: `make_entity_id(source_path)` returns UUID5 (deterministic) from
the source path. Slug is a separate column for filenames and link resolution.

Version columns (`compiler_version`, `extractor_version`, `tokenizer_version`)
per entity auto-invalidate cache when tooling changes.

---

## Phase 2 — Streaming Pipeline ✅

**Files**: `src/compiler.py` rewritten with `Compiler`, `CompilePlanner`,
`CompileEvent`, `CompileStats`, `CompileResult`, `ChangeSet`, `CompilerConfig`.
`compile_wiki()` kept as backward-compat wrapper.

`SourceProvider` ABC with `Document` ABC. `FilesystemProvider` scans for
all supported formats (`.txt`, `.md`, `.docx`, `.pdf`, etc.).

**Tests**: 14 Compiler tests.

---

## Phase 3 — Content Hashing + Change Detection ✅

**Files**: `ChangeDetector` class in `compiler.py` — version staleness →
mtime/size fast skip → SHA-256 hash comparison → deleted-file detection.

Three hashes per entity: `source_hash`, `body_hash`, `metadata_hash`.

**Tests**: 7 ChangeDetector tests + 6 CompilePlannerWithStore tests.

---

## Phase 4 — Incremental Graph ✅

**Files**: `GraphBuilder` ABC + `WordIndexGraphBuilder` in `graph.py`.
`GraphBuilderResult` dataclass. `get_all_outgoing()` on `GraphRepo`.

**Bug fix**: removed `delete_incoming` from Phase 1b (was destroying edges
from other changed entities).

**Tests**: 4 GraphBuilder tests.

---

## Phase 5 — Parallel Extraction ✅

**Module**: `concurrent.futures.ProcessPoolExecutor` with `executor.map()`
(preserves submission order → deterministic output).

`_parallel_extract()` module-level worker handles `sys.path` setup for
subprocesses.

**Tests**: 6 ParallelExtraction tests.

---

## Phase 6 — Plugin Interfaces ✅

**File**: `src/plugin.py` — `Plugin`, `Extractor`, `Renderer`, `Validator`,
`LinkResolver` ABCs. Default implementations: `TxtExtractor`,
`MarkdownRenderer`, `WikiLinter`, `WikiLinkResolver`.

`GraphBuilder` now extends `Plugin`. `Compiler` manages lifecycle
(`initialize`/`shutdown` via `try/finally` in `compile_events`).

**Tests**: 8 Plugin tests.

---

## Phase 7 — Watch Mode ✅

**File**: `src/watcher.py` — polling-based file watcher. `Compiler.watch()`
delegates to `watcher.watch()`. CLI `--watch` / `-w` with `--poll-interval`.

**Polling algorithm**: mtime/size comparison, full incremental recompile on
any change. `max_cycles` param for testability.

**Tests**: 9 Watcher tests (scan, detect new/modified/deleted/no-change,
initial compile, recompile on change).

---

## Additional — MarkItDown Converter ✅

**File**: `src/converter.py` — wraps MarkItDown for document conversion.
`FilesystemProvider.iter_documents()` yields `FilesystemDocument` for
`.txt`/`.md` and `ConvertingDocument` for other formats.

`extract_entity(path, content=None)` accepts pre-converted content string
so the pipeline works seamlessly with converted documents.

**Tests**: 12 Converter tests + 4 SourceProviderMultiFormat tests + 3
ExtractorWithContent tests.

---

## Final state

| Metric | Value |
|--------|-------|
| Source files | 17 modules in `src/` |
| Tests | 125 (stdlib unittest) |
| Runtime deps | `markitdown` (multi-format conversion) |
| Lint | `ruff check src/` clean |
| Typecheck | `mypy src/` clean |
| Python | 3.12+ |

## Performance targets

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

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| Bodies on filesystem, not SQLite | Prevents multi-GB database for large corpora |
| ContentRepository (5th repo) | Renderer accesses content via store, not filesystem directly |
| UUID5 (deterministic) over UUID4 | Same path → same ID. Cache survives rebuilds. |
| Store split into 5 repos | Focused interfaces; replace independently |
| EntityRepo returns iterators, not dicts | Avoids memory explosion at scale |
| CompilePlanner with stage methods | Explicit workflow engine; Compiler stays thin |
| Transaction context manager | Cleaner than raw BEGIN/COMMIT; harder to misuse |
| Schema migrations | Never DROP DATABASE; forward-compatible |
| SourceProvider with Document.id | Stable ID across filesystem, Git, S3 sources |
| LinkResolver ABC | Wiki syntax isolated from core pipeline |
| GraphBuilder ABC | Graph algorithm replaceable independently |
| Plugin lifecycle hooks | Resource cleanup, initialization guarantees |
| Version columns per entity | Auto-invalidate cache when tooling changes |
| Dependency Injection | All deps injectable; plain config as default |
| executor.map() over as_completed() | Preserves submission order; deterministic events |
| ChangeSet (not plain set[str]) | Captures added/deleted/renamed/unchanged explicitly |
| CompileEvent dataclass | Typed events instead of raw dicts |
| MarkItDown for multi-format input | One dependency unlocks 10+ input formats |
| Polling watcher over inotify/kqueue | Cross-platform, stdlib-only, testable |
