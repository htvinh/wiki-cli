# Implementation Plan — Complete

All phases implemented. Current state: 136 tests, 4-stage pipeline.

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
 Converter Extractor GraphBuilder Renderer  Validator
  └──────────┴────────────┴──────────┴────────────┘
                        │
              RelationshipEngine
             (nav / link / folder)
```

## Final state

| Metric | Value |
|--------|-------|
| Source files | 17 modules in `src/` |
| Tests | 136 (stdlib unittest) |
| Runtime deps | `markitdown` (multi-format conversion) |
| Lint | `ruff check src/` clean |
| Typecheck | `mypy src/` clean |
| Python | 3.12+ |

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| Three-graph engine (nav/link/folder) | Separate concerns: hierarchy, mentions, folder structure |
| Related page scoring | Deterministic, no LLM, no embeddings |
| Bodies on filesystem, not SQLite | Prevents multi-GB database for large corpora |
| UUID5 (deterministic) over UUID4 | Same path → same ID. Cache survives rebuilds. |
| Store split into 5 repos | Focused interfaces; replace independently |
| CompilePlanner with stage methods | Explicit workflow engine; Compiler stays thin |
| Schema migrations | Never DROP DATABASE; forward-compatible |
| GraphBuilder + Plugin ABCs | Graph algorithm replaceable independently |
| executor.map() over as_completed() | Preserves submission order; deterministic events |
| ChangeSet (not plain set[str]) | Captures added/deleted/renamed/unchanged explicitly |
| CompileEvent dataclass | Typed events instead of raw dicts |
| MarkItDown for multi-format input | One dependency unlocks 10+ input formats |
| index.md + index.html per directory | Browseable output for both markdown and web