"""
compiler.py

Compiler class, CompilePlanner, ChangeDetector, and supporting dataclasses
for the deterministic wiki compilation pipeline.
"""

import argparse
import hashlib
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Generator

from extractor import Entity, extract_all, extract_entity
from graph import (
    GraphBuilder,
    GraphReport,
    WordIndexGraphBuilder,
    build_graph,
    build_navigation_edges,
    graph_report,
)
from linter import LintReport, lint, print_report
from rewriter import compile_pages
from source import FilesystemProvider, SourceProvider
from store import (
    CURRENT_COMPILER_VERSION,
    CURRENT_EXTRACTOR_VERSION,
    CURRENT_TOKENIZER_VERSION,
    Store,
    make_entity_id,
)

logger = logging.getLogger(__name__)


# ── Worker function for ProcessPoolExecutor ────────────────────────────


def _parallel_extract(args: tuple[str, bytes]) -> Entity | None:
    """Module-level worker: extract from a (path, content_bytes) pair."""
    path, content_bytes = args
    try:
        import sys as _sys
        _src = os.path.dirname(os.path.abspath(__file__))
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
        from extractor import extract_entity as _ee
        return _ee(path, content=content_bytes.decode("utf-8"))
    except Exception:
        logger = logging.getLogger(__name__)
        logger.exception("Extraction failed for %s", path)
        return None


def _extract_sequential(docs: list) -> dict[str, Entity]:
    entities: dict[str, Entity] = {}
    for doc in docs:
        content = doc.read_bytes().decode("utf-8")
        entity = extract_entity(doc.path, content=content)
        entities[entity.entity_id] = entity
    logger.info("Extracted %d entities (sequential)", len(entities))
    return entities


def _extract_parallel(docs: list, workers: int) -> dict[str, Entity]:
    args = [(doc.path, doc.read_bytes()) for doc in docs]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_parallel_extract, args))
    entities = {e.entity_id: e for e in results if e is not None}
    logger.info("Extracted %d entities (parallel, workers=%d)",
                len(entities), workers)
    return entities


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class CompileEvent:
    event: str
    phase: str
    timestamp: float
    entity_id: str | None = None
    elapsed: float | None = None
    payload: dict | None = None


@dataclass
class ChangeSet:
    added: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    renamed: dict[str, str] = field(default_factory=dict)
    unchanged: set[str] = field(default_factory=set)


@dataclass
class CompileStats:
    entity_count: int = 0
    edge_count: int = 0
    pages_changed: int = 0
    pages_skipped: int = 0
    added: int = 0
    deleted: int = 0
    renamed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_ratio: float = 0.0
    broken_links: int = 0
    lexical_unlinked: int = 0
    elapsed_s: float = 0.0
    entities_per_sec: float = 0.0
    pages_per_sec: float = 0.0
    graph_time_s: float = 0.0
    hash_time_s: float = 0.0
    sqlite_time_s: float = 0.0
    io_time_s: float = 0.0
    peak_memory_mb: float = 0.0
    sqlite_size_kb: int = 0
    body_cache_size_kb: int = 0


@dataclass
class CompileResult:
    pages_written: int
    lint_report: LintReport | None
    stats: CompileStats
    graph_report: GraphReport | None = None


@dataclass
class CompilerConfig:
    cache_dir: str = ".cache"
    workers: int = 1
    lint: bool = True
    incremental: bool = True
    parallel: bool = False
    navigation_hubs: int = 0
    source_provider: SourceProvider | None = None
    extractors: list | None = None
    renderers: list | None = None
    validators: list | None = None
    link_resolver: object | None = None


# ── ChangeDetector ────────────────────────────────────────────────────


class ChangeDetector:
    def __init__(self, store: Store):
        self._store = store

    def detect(self, provider: SourceProvider, raw_dir: str) -> ChangeSet:
        known_ids = set(self._store.entities.iter_ids())
        added: set[str] = set()
        modified: set[str] = set()
        unchanged: set[str] = set()
        deleted: set[str] = set()

        seen_ids: set[str] = set()
        for doc in provider.iter_documents(raw_dir):
            eid = make_entity_id(os.path.abspath(doc.path))
            seen_ids.add(eid)
            entity = self._store.entities.get(eid)
            if entity is None:
                added.add(eid)
                continue

            if self._is_version_stale(entity):
                modified.add(eid)
                continue

            if (float(entity.get("mtime", 0)) == doc.mtime
                    and int(entity.get("size", 0)) == doc.size):
                unchanged.add(eid)
                continue

            source_hash = hashlib.sha256(doc.read_bytes()).hexdigest()
            if source_hash == entity.get("source_hash", ""):
                unchanged.add(eid)
            else:
                modified.add(eid)

        for known_id in known_ids:
            if known_id not in seen_ids:
                deleted.add(known_id)

        return ChangeSet(
            added=added,
            modified=modified,
            deleted=deleted,
            unchanged=unchanged,
        )

    def _is_version_stale(self, entity: dict) -> bool:
        return any([
            entity.get("compiler_version", "") != CURRENT_COMPILER_VERSION,
            entity.get("extractor_version", "") != CURRENT_EXTRACTOR_VERSION,
            entity.get("tokenizer_version", "") != CURRENT_TOKENIZER_VERSION,
        ])


# ── CompilePlanner ───────────────────────────────────────────────────

class CompilePlanner:
    def __init__(self, config: CompilerConfig | None = None,
                 store: Store | None = None,
                 graph_builder: GraphBuilder | None = None):
        self.config = config or CompilerConfig()
        self._store = store
        self._detector = ChangeDetector(store) if store else None
        nav = self.config.navigation_hubs
        self._graph_builder = (
            graph_builder
            or (WordIndexGraphBuilder(navigation_hubs=nav) if store else None)
        )

    def detect_changes(self, source_provider: SourceProvider,
                       raw_dir: str) -> ChangeSet:
        if self._detector:
            return self._detector.detect(source_provider, raw_dir)
        docs = list(source_provider.iter_documents(raw_dir))
        return ChangeSet(added={doc.id for doc in docs})

    def remove_deleted(self, deleted_ids: set[str],
                       output_dir: str) -> None:
        if not self._store or not deleted_ids:
            return
        for eid in deleted_ids:
            entity = self._store.entities.get(eid)
            slug = entity["slug"] if entity else eid
            self._store.entities.delete(eid)
            self._store.graph.delete_outgoing(eid)
            self._store.graph.delete_incoming(eid)
            self._store.index.drop_entity_index(eid)
            self._store.content.delete(eid)
            out = os.path.join(output_dir, f"{slug}.md")
            if os.path.exists(out):
                os.remove(out)
                logger.info("Removed deleted page: %s", out)

    def extract(self, source_provider: SourceProvider, raw_dir: str,
                changes: ChangeSet) -> dict[str, Entity]:
        docs = list(source_provider.iter_documents(raw_dir))
        workers = self.config.workers
        if workers > 1 and len(docs) > 1:
            return _extract_parallel(docs, workers)
        return _extract_sequential(docs)

    def graph(self, entities: dict[str, Entity],
              changes: ChangeSet | None = None) -> dict:
        if self._graph_builder and self._store and changes is not None:
            result = self._graph_builder.build(changes, self._store, entities)
            return result.graph
        g = build_graph(entities)
        if self.config.navigation_hubs > 0:
            g = build_navigation_edges(g, entities,
                                       top_n=self.config.navigation_hubs)
        return g

    def render(self, entities: dict[str, Entity], graph: dict,
               output_dir: str, raw_dir: str = "") -> list[str]:
        return compile_pages(entities, graph, output_dir, raw_dir)

    def validate(self, output_dir: str) -> LintReport:
        return lint(output_dir)


# ── Compiler ─────────────────────────────────────────────────────────

class Compiler:
    def __init__(
        self,
        config: CompilerConfig | None = None,
        planner: CompilePlanner | None = None,
        source_provider: SourceProvider | None = None,
        store: Store | None = None,
        graph_builder: GraphBuilder | None = None,
    ):
        self.config = config or CompilerConfig()
        self._store = store
        self._source_provider = source_provider
        if planner is not None:
            self.planner = planner
        else:
            self.planner = CompilePlanner(config=self.config, store=store,
                                          graph_builder=graph_builder)
        self._result: CompileResult | None = None
        self._plugins = self._collect_plugins()

    def _collect_plugins(self) -> list:
        plugins: list = []
        if self.planner._graph_builder is not None:
            plugins.append(self.planner._graph_builder)
        if self.config.extractors:
            plugins.extend(self.config.extractors)
        if self.config.renderers:
            plugins.extend(self.config.renderers)
        if self.config.validators:
            plugins.extend(self.config.validators)
        if self.config.link_resolver:
            plugins.append(self.config.link_resolver)
        return plugins

    def _resolve_provider(self) -> SourceProvider:
        return (self._source_provider
                or self.config.source_provider
                or FilesystemProvider())

    def compile(self, raw_dir: str, output_dir: str) -> CompileResult:
        for _ in self.compile_events(raw_dir, output_dir):
            pass
        assert self._result is not None
        return self._result

    def compile_events(
        self, raw_dir: str, output_dir: str
    ) -> Generator[CompileEvent, None, CompileResult]:
        self._last_entities: dict | None = None
        provider = self._resolve_provider()
        start = time.perf_counter()

        for p in self._plugins:
            p.initialize(self.config)

        try:
            yield CompileEvent("phase_start", "detect", start,
                               payload={"raw_dir": raw_dir})
            changes = self.planner.detect_changes(provider, raw_dir)
            yield CompileEvent("phase_end", "detect", time.perf_counter(),
                               elapsed=time.perf_counter() - start,
                               payload={
                                   "total": len(changes.added),
                                   "added": len(changes.added),
                                   "modified": len(changes.modified),
                                   "deleted": len(changes.deleted),
                                   "unchanged": len(changes.unchanged),
                               })

            # remove deleted
            if changes.deleted:
                yield CompileEvent("phase_start", "remove_deleted",
                                   time.perf_counter(),
                                   payload={"count": len(changes.deleted)})
                self.planner.remove_deleted(changes.deleted, output_dir)
                yield CompileEvent("phase_end", "remove_deleted",
                                   time.perf_counter())

            # extract
            t0 = time.perf_counter()
            yield CompileEvent("phase_start", "extract", t0)
            entities = self.planner.extract(provider, raw_dir, changes)
            self._last_entities = entities
            for eid in entities:
                yield CompileEvent("extracted", "extract",
                                   time.perf_counter(), entity_id=eid)
            yield CompileEvent("phase_end", "extract", time.perf_counter(),
                               elapsed=time.perf_counter() - t0,
                               payload={"entity_count": len(entities)})

            # graph
            t0 = time.perf_counter()
            yield CompileEvent("phase_start", "graph", t0)
            graph = self.planner.graph(entities, changes=changes)
            graph_time = time.perf_counter() - t0
            edge_count = sum(len(v["outgoing"]) for v in graph.values())
            yield CompileEvent("phase_end", "graph", time.perf_counter(),
                               elapsed=graph_time,
                               payload={"edge_count": edge_count})

            # render
            t0 = time.perf_counter()
            yield CompileEvent("phase_start", "render", t0)
            written = self.planner.render(entities, graph, output_dir, raw_dir)
            for path in written:
                yield CompileEvent("written", "render",
                                   time.perf_counter(),
                                   entity_id=os.path.basename(path))
            render_time = time.perf_counter() - t0
            yield CompileEvent("phase_end", "render", time.perf_counter(),
                               elapsed=render_time,
                               payload={"pages_written": len(written)})

            # lint
            lint_report = None
            if self.config.lint:
                t0 = time.perf_counter()
                yield CompileEvent("phase_start", "lint", t0)
                lint_report = self.planner.validate(output_dir)
                yield CompileEvent("lint_result", "lint", time.perf_counter(),
                                   payload={
                                       "broken": len(lint_report.broken_links),
                                        "lexical_unlinked": len(lint_report.lexical_unlinked_pages),
                                   })
                yield CompileEvent("phase_end", "lint", time.perf_counter(),
                                   elapsed=time.perf_counter() - t0)

            # graph report
            g_report = graph_report(graph, entities)

            # done
            elapsed = time.perf_counter() - start
            total_unchanged = len(changes.unchanged) if hasattr(
                changes, "unchanged") else 0
            yield CompileEvent("done", "", time.perf_counter())

            stats = CompileStats(
                entity_count=len(entities),
                edge_count=edge_count,
                pages_changed=len(written),
                pages_skipped=total_unchanged,
                added=len(changes.added),
                deleted=len(changes.deleted),
                broken_links=(len(lint_report.broken_links)
                              if lint_report else 0),
                lexical_unlinked=(len(lint_report.lexical_unlinked_pages)
                                  if lint_report else 0),
                elapsed_s=elapsed,
                entities_per_sec=(len(entities) / elapsed
                                  if elapsed > 0 else 0.0),
                pages_per_sec=(len(written) / elapsed
                               if elapsed > 0 else 0.0),
                graph_time_s=graph_time,
            )
            result = CompileResult(
                pages_written=len(written),
                lint_report=lint_report,
                stats=stats,
                graph_report=g_report,
            )
            self._result = result
            return result

        finally:
            for p in reversed(self._plugins):
                p.shutdown()

# ── Backward-compat wrapper ──────────────────────────────────────────

def compile_wiki(raw_dir: str, output_dir: str, run_lint: bool = True) -> dict:
    entities = extract_all(raw_dir)
    graph = build_graph(entities)
    written = compile_pages(entities, graph, output_dir)
    logger.info("Compiled %d pages from %s -> %s", len(written), raw_dir, output_dir)

    report = None
    if run_lint:
        report = lint(output_dir)

    return {
        "entities": entities,
        "graph": graph,
        "written_paths": written,
        "lint_report": report,
    }


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile raw notes into a linked markdown wiki."
    )
    parser.add_argument("raw_dir", help="Directory of raw source files")
    parser.add_argument("output_dir", nargs="?", default=None,
                        help="Directory to write compiled .md pages into (default: raw_dir-wiki)")
    parser.add_argument("--no-lint", action="store_true", help="Skip the lint pass")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel extraction workers (default: 1)")
    parser.add_argument("--report", action="store_true",
                        help="Print graph report after compilation")
    args = parser.parse_args()
    if args.output_dir is None:
        args.output_dir = args.raw_dir.rstrip("/") + "-wiki"

    config = CompilerConfig(
        lint=not args.no_lint,
        workers=args.workers,
    )
    compiler = Compiler(config=config)

    progress_chars = 0
    for event in compiler.compile_events(args.raw_dir, args.output_dir):
        if event.event == "extracted":
            sys.stdout.write(".")
            sys.stdout.flush()
            progress_chars += 1
        elif event.event == "phase_end" and event.phase == "extract":
            if progress_chars > 0:
                sys.stdout.write("\n")
                sys.stdout.flush()
    result = compiler._result
    assert result is not None
    print(
        f"Compiled {result.pages_written} pages "
        f"from {args.raw_dir} -> {args.output_dir}"
    )
    if result.lint_report:
        print_report(result.lint_report)
    if args.report and result.graph_report:
        from graph import print_graph_report
        print_graph_report(result.graph_report,
                           entities=compiler._last_entities)
    return 0


if __name__ == "__main__":
    main()
