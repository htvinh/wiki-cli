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

from plugin import Plugin
from store import Store

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\w']+")


def _build_phrase_index(entities: dict) -> dict:
    index: dict = {}
    for eid, ent in entities.items():
        words = tuple(w.lower() for w in _WORD_RE.findall(ent.name))
        if not words:
            continue
        index.setdefault(words[0], []).append((words, eid))

    for first_word in index:
        index[first_word].sort(key=lambda pair: -len(pair[0]))

    return index


def build_graph(entities: dict) -> dict:
    graph: dict[str, dict[str, set]] = {
        eid: {"outgoing": set(), "incoming": set()}
        for eid in entities
    }

    if not entities:
        return graph

    phrase_index = _build_phrase_index(entities)

    for eid, ent in entities.items():
        tokens = [w.lower() for w in _WORD_RE.findall(ent.body)]
        seen_targets: set = set()
        n = len(tokens)
        i = 0
        while i < n:
            candidates = phrase_index.get(tokens[i])
            if candidates:
                for words, target_id in candidates:
                    end = i + len(words)
                    if end <= n and tuple(tokens[i:end]) == words:
                        if target_id != eid:
                            seen_targets.add(target_id)
                        break
            i += 1

        for target_id in seen_targets:
            graph[eid]["outgoing"].add(target_id)
            graph[target_id]["incoming"].add(eid)

    edge_count = sum(len(v["outgoing"]) for v in graph.values())
    logger.info("Built graph: %d entities, %d edges", len(entities), edge_count)
    return graph


def orphan_ids(graph: dict) -> list:
    return sorted(
        eid for eid, edges in graph.items()
        if not edges["incoming"]
    )


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
    def build(self, changes, store: Store, entities: dict) -> GraphBuilderResult:
        start = time.perf_counter()
        changed_ids = changes.added | changes.modified
        changed_edges = 0

        with store.transaction():
            # Phase 1a: re-index all changed entities' names so the
            # word_index is up to date before any body scan.
            for eid in changed_ids:
                store.index.drop_entity_index(eid)
                entity = entities.get(eid)
                if entity is not None:
                    store.index.index_name(eid, entity.name)

            # Phase 1b: scan changed entities' bodies for mentions.
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
                    store.graph.put_edge(eid, target_id)
                    changed_edges += 1

            # Phase 2: re-scan entities whose name shares a word with a
            # changed entity — they may now link to it.
            for eid in changed_ids:
                entity = entities.get(eid)
                if entity is None:
                    continue
                name_words = set(w.lower()
                                 for w in _WORD_RE.findall(entity.name))
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
                        store.graph.put_edge(cid, eid)
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
