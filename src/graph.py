"""
graph.py

Stage 2: given extracted entities, detects mentions of one entity's name
inside another entity's body text and builds a bidirectional map.

Also defines the GraphBuilder ABC and WordIndexGraphBuilder for
store-backed incremental graph construction.
"""

import logging
import re
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from plugin import Plugin
from store import Store

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\w']+")


class EdgeType(Enum):
    EXPLICIT = "explicit"      # name mention in body text
    ALIAS = "alias"            # alias / redirect match
    NAVIGATION = "navigation"  # popular / navigational link
    RELATED = "related"        # keyword-, heading-, or TF-IDF-based


@dataclass
class Edge:
    source: str
    target: str
    edge_type: EdgeType = EdgeType.EXPLICIT
    provenance: str = ""
    confidence: float = 1.0


def _build_phrase_index(entities: dict) -> dict:
    index: dict = {}
    for eid, ent in entities.items():
        words = tuple(w.lower() for w in _WORD_RE.findall(ent.name))
        if not words:
            continue
        index.setdefault(words[0], []).append((words, eid, "name"))

    for first_word in index:
        index[first_word].sort(key=lambda pair: -len(pair[0]))

    return index


def _build_alias_index(entities: dict) -> dict:
    index: dict = {}
    for eid, ent in entities.items():
        for alias in ent.aliases:
            words = tuple(w.lower() for w in _WORD_RE.findall(alias))
            if not words:
                continue
            index.setdefault(words[0], []).append((words, eid))
    for first_word in index:
        index[first_word].sort(key=lambda pair: -len(pair[0]))
    return index


def build_graph(entities: dict, edge_type: EdgeType = EdgeType.EXPLICIT) -> dict:
    graph: dict[str, dict[str, set]] = {
        eid: {"outgoing": set(), "incoming": set()}
        for eid in entities
    }

    if not entities:
        return graph

    phrase_index = _build_phrase_index(entities)
    alias_index = _build_alias_index(entities)

    for eid, ent in entities.items():
        tokens = [w.lower() for w in _WORD_RE.findall(ent.body)]
        seen_targets: set = set()
        alias_targets: set = set()
        n = len(tokens)
        i = 0
        while i < n:
            candidates = phrase_index.get(tokens[i])
            if candidates:
                for words, target_id, _kind in candidates:
                    end = i + len(words)
                    if end <= n and tuple(tokens[i:end]) == words:
                        if target_id != eid:
                            seen_targets.add(target_id)
                        break
            i += 1

        for target_id in seen_targets:
            graph[eid]["outgoing"].add(target_id)
            graph[target_id]["incoming"].add(eid)

        # Alias scan
        if alias_index:
            i = 0
            while i < n:
                candidates = alias_index.get(tokens[i])
                if candidates:
                    for words, target_id in candidates:
                        end = i + len(words)
                        if end <= n and tuple(tokens[i:end]) == words:
                            if target_id != eid and target_id not in seen_targets:
                                alias_targets.add(target_id)
                            break
                i += 1
            for target_id in alias_targets:
                graph[eid]["outgoing"].add(target_id)
                graph[target_id]["incoming"].add(eid)

    edge_count = sum(len(v["outgoing"]) for v in graph.values())
    logger.info(
        "Built graph: %d entities, %d edges (%s)",
        len(entities), edge_count, edge_type.value,
    )
    return graph


def orphan_ids(graph: dict) -> list:
    return sorted(
        eid for eid, edges in graph.items()
        if not edges["incoming"]
    )


def build_navigation_edges(graph: dict, entities: dict,
                           top_n: int = 5) -> dict:
    if top_n < 1 or not entities:
        return graph

    counts: dict[str, int] = {}
    for eid, edges in graph.items():
        counts[eid] = len(edges["incoming"])

    sorted_entities = sorted(counts.items(), key=lambda x: -x[1])
    hubs = [eid for eid, _ in sorted_entities[:top_n]]

    if not hubs:
        return graph

    for eid in graph:
        for hub_id in hubs:
            if hub_id != eid:
                graph[eid]["outgoing"].add(hub_id)
                graph[hub_id]["incoming"].add(eid)

    logger.info("Added %d navigation edges (top %d hubs)",
                len(hubs) * (len(graph) - 1), top_n)
    return graph


# ── Graph report ─────────────────────────────────────────────────────


@dataclass
class GraphReport:
    entity_count: int = 0
    edge_count: int = 0
    top_linked: list = field(default_factory=list)
    top_referencing: list = field(default_factory=list)
    lexical_unlinked: list = field(default_factory=list)


def graph_report(graph: dict, entities: dict | None = None,
                 top_n: int = 10) -> GraphReport:
    report = GraphReport(
        entity_count=len(graph),
        edge_count=sum(len(v["outgoing"]) for v in graph.values()),
    )

    incoming_counts: list[tuple[str, int]] = sorted(
        ((eid, len(edges["incoming"])) for eid, edges in graph.items()),
        key=lambda x: -x[1],
    )
    outgoing_counts: list[tuple[str, int]] = sorted(
        ((eid, len(edges["outgoing"])) for eid, edges in graph.items()),
        key=lambda x: -x[1],
    )

    report.top_linked = incoming_counts[:top_n]
    report.top_referencing = outgoing_counts[:top_n]

    report.lexical_unlinked = sorted(
        eid for eid, edges in graph.items()
        if not edges["incoming"]
    )

    return report


def print_graph_report(report: GraphReport,
                       entities: dict | None = None) -> None:
    def _name(eid: str) -> str:
        if entities and eid in entities:
            return entities[eid].name
        return eid

    print(f"Graph report: {report.entity_count} entities, "
          f"{report.edge_count} edges")
    print(f"  Lexically unlinked: {len(report.lexical_unlinked)}")

    if report.top_linked:
        print("\n  Top-linked (most incoming):")
        for eid, count in report.top_linked[:5]:
            if count > 0:
                print(f"    {_name(eid)} ({count})")

    if report.top_referencing:
        print("\n  Top-referencing (most outgoing):")
        for eid, count in report.top_referencing[:5]:
            if count > 0:
                print(f"    {_name(eid)} ({count})")


# ── GraphBuilder ABC ─────────────────────────────────────────────────


@dataclass
class GraphBuilderResult:
    edge_count: int = 0
    changed_edges: int = 0
    elapsed_s: float = 0.0
    graph: dict = field(default_factory=dict)


class GraphBuilder(Plugin):
    @abstractmethod
    def build(self, changes, store: Store, entities: dict) -> GraphBuilderResult:
        ...


class WordIndexGraphBuilder(GraphBuilder):
    def __init__(self, navigation_hubs: int = 0):
        self._navigation_hubs = navigation_hubs

    def build(self, changes, store: Store, entities: dict) -> GraphBuilderResult:
        start = time.perf_counter()
        changed_ids = changes.added | changes.modified
        changed_edges = 0

        with store.transaction():
            # Phase 1a: re-index all changed entities' names and aliases
            # so the word_index is up to date before any body scan.
            for eid in changed_ids:
                store.index.drop_entity_index(eid)
                entity = entities.get(eid)
                if entity is not None:
                    store.index.index_name(eid, entity.name)
                    for alias in entity.aliases:
                        store.index.index_alias(eid, alias)

            # Phase 1b: scan changed entities' bodies for name mentions.
            # Only delete outgoing edges — incoming edges from other
            # changed entities haven't been re-scanned yet and would
            # be incorrectly removed here.
            for eid in changed_ids:
                store.graph.delete_outgoing(eid)
                entity = entities.get(eid)
                if entity is None:
                    continue

                tokens = [w.lower() for w in _WORD_RE.findall(entity.body)]
                n = len(tokens)
                targets: set[str] = set()
                alias_targets: set[str] = set()
                i = 0
                while i < n:
                    for cid in store.index.get_candidates(tokens[i]):
                        if cid == eid:
                            continue
                        cents = store.entities.get(cid)
                        if cents is None:
                            continue
                        cname = cents.get("name", "")
                        cwords = [w.lower() for w in _WORD_RE.findall(cname)]
                        end = i + len(cwords)
                        if end <= n and tokens[i:end] == cwords:
                            targets.add(cid)
                            break
                    i += 1

                for target_id in targets:
                    store.graph.put_edge(eid, target_id, EdgeType.EXPLICIT)
                    changed_edges += 1

                # Phase 1c: scan for alias mentions — same body, different
                # match target. We iterate again to keep each phase clean.
                i = 0
                while i < n:
                    for cid in store.index.get_candidates(tokens[i]):
                        if cid == eid or cid in targets:
                            continue
                        cents = store.entities.get(cid)
                        if cents is None:
                            continue
                        caliases_str = cents.get("aliases", "")
                        if not caliases_str:
                            continue
                        for alias in (a.strip() for a in caliases_str.split(",") if a.strip()):
                            awords = [w.lower() for w in _WORD_RE.findall(alias)]
                            end = i + len(awords)
                            if end <= n and tokens[i:end] == awords:
                                alias_targets.add(cid)
                                break
                    i += 1

                for target_id in alias_targets:
                    store.graph.put_edge(eid, target_id, EdgeType.ALIAS)
                    changed_edges += 1

            # Phase 2: re-scan entities whose name or alias shares a word
            # with a changed entity — they may now link to it.
            for eid in changed_ids:
                entity = entities.get(eid)
                if entity is None:
                    continue
                name_words = set(w.lower()
                                 for w in _WORD_RE.findall(entity.name))
                for alias in entity.aliases:
                    name_words.update(w.lower() for w in _WORD_RE.findall(alias))
                affected: set[str] = set()
                for word in name_words:
                    for cid in store.index.get_candidates(word):
                        if cid != eid and cid not in changed_ids:
                            affected.add(cid)

                ename_lower = entity.name.lower()
                for cid in affected:
                    cents = store.entities.get(cid)
                    if cents is None:
                        continue
                    cbody = store.content.get(cid)
                    if cbody is None:
                        entity_obj = entities.get(cid)
                        if entity_obj is not None:
                            cbody = entity_obj.body
                    if cbody is not None and ename_lower in cbody.lower():
                        store.graph.put_edge(cid, eid, EdgeType.EXPLICIT)
                        changed_edges += 1

        # Phase 4: add navigation edges to most-linked hubs.
        if self._navigation_hubs > 0:
            all_outgoing = store.graph.get_all_outgoing()
            incoming_counts: dict[str, int] = {}
            for src, targets in all_outgoing.items():
                for t in targets:
                    incoming_counts[t] = incoming_counts.get(t, 0) + 1
            sorted_ids = sorted(incoming_counts,
                                key=lambda eid: incoming_counts.get(eid, 0),
                                reverse=True)
            hubs = set(sorted_ids[:self._navigation_hubs])
            if hubs:
                for eid in entities:
                    if eid not in hubs:
                        for hub_id in hubs:
                            store.graph.put_edge(eid, hub_id,
                                                 EdgeType.NAVIGATION)
                            changed_edges += 1

        # Phase 3: build full in-memory graph dict from store.
        all_outgoing = store.graph.get_all_outgoing()
        graph: dict[str, dict[str, set]] = {}
        for eid in entities:
            outgoing = all_outgoing.get(eid, set())
            incoming: set[str] = set()
            for src, targets in all_outgoing.items():
                if eid in targets:
                    incoming.add(src)
            graph[eid] = {"outgoing": outgoing, "incoming": incoming}

        elapsed = time.perf_counter() - start
        edge_count = store.graph.get_edge_count()

        return GraphBuilderResult(
            edge_count=edge_count,
            changed_edges=changed_edges,
            elapsed_s=elapsed,
            graph=graph,
        )


if __name__ == "__main__":
    from extractor import extract_all

    logging.basicConfig(level=logging.INFO)
    ents = extract_all("raw_notes")
    g = build_graph(ents)
    total_edges = sum(len(v["outgoing"]) for v in g.values())
    print(f"Entities: {len(ents)}, directed edges: {total_edges}")
    print(f"Orphans: {orphan_ids(g)}")
