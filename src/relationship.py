"""
relationship.py

Three-graph builder: navigation (folder hierarchy), folder (parent/child/sibling),
and link (lexical [[Page]]). Exposes compute_related() and compute_backlinks()
for page generation, plus unreachable detection for linting.
"""

import logging
import os
import re

from extractor import Entity
from store import Store

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\w']+")

NAV = "navigation"
LINK = "lexical"
FOLDER = "folder"


class RelationshipEngine:
    def __init__(self, store: Store):
        self._store = store

    def build_all(self, entities: dict[str, Entity]) -> int:
        count = 0
        paths_by_eid: dict[str, str] = {}
        for eid, ent in entities.items():
            paths_by_eid[eid] = ent.source_path

        eid_by_path: dict[str, str] = {}
        for eid, path in paths_by_eid.items():
            parent_dir = os.path.dirname(path)
            if parent_dir and parent_dir in eid_by_path:
                parent_id = eid_by_path[parent_dir]
                with self._store.transaction():
                    self._store.graph.put_edge(eid, parent_id, "parent", NAV)
                    self._store.graph.put_edge(parent_id, eid, "child", NAV)
                    count += 2

        return count

    def compute_related(self, entity_id: str, entities: dict[str, Entity],
                        top_k: int = 5) -> list[tuple[str, str]]:
        scores: dict[str, int] = {}
        entity = entities.get(entity_id)
        if entity is None:
            return []

        my_parent: str | None = None

        parent_out = self._store.graph.get_outgoing(entity_id, NAV)
        for p in parent_out:
            if self._store.graph.get_edge_type(entity_id, p, NAV) == "parent":
                my_parent = p
                break

        siblings: set[str] = set()
        if my_parent:
            children = self._store.graph.get_outgoing(my_parent, NAV)
            siblings = {c for c in children if c != entity_id}

        lexical_out = self._store.graph.get_outgoing(entity_id, LINK)
        lexical_in = self._store.graph.get_incoming(entity_id, LINK)

        candidates: set[str] = set()
        if my_parent:
            candidates.add(my_parent)
        candidates.update(siblings)
        candidates.update(lexical_out)
        candidates.update(lexical_in)

        my_words = set(_WORD_RE.findall(entity.body.lower())) if entity.body else set()
        my_name_words = set(entity.name.lower().split()) if entity.name else set()

        for candidate_id in candidates:
            score = 0
            cand = entities.get(candidate_id)
            if cand is None:
                continue

            if candidate_id in siblings:
                score += 5

            if candidate_id == my_parent:
                score += 3

            if candidate_id in lexical_out:
                score += 3

            if candidate_id in lexical_in:
                score += 2

            if cand.body:
                cand_words = set(_WORD_RE.findall(cand.body.lower()))
                overlap = my_words & cand_words
                if overlap:
                    score += min(2, len(overlap) // 5)

            if cand.name:
                cand_name_words = set(cand.name.lower().split())
                overlap = my_name_words & cand_name_words
                if overlap:
                    score += 1

            scores[candidate_id] = score

        def _sort_key(item):
            _eid, _score = item
            ent = entities.get(_eid)
            return (-_score, ent.name if ent else _eid)

        ranked = sorted(scores.items(), key=_sort_key)
        return [(eid, entities[eid].name) for eid, _ in ranked[:top_k] if eid in entities]

    def compute_backlinks(self, entity_id: str,
                          entities: dict[str, Entity]) -> list[tuple[str, str]]:
        all_incoming: set[str] = set()
        all_incoming.update(self._store.graph.get_incoming(entity_id, LINK))
        all_incoming.update(self._store.graph.get_incoming(entity_id, NAV))

        def _key(eid):
            ent = entities.get(eid)
            return ent.name if ent else eid

        sorted_ids = sorted(all_incoming, key=_key)
        return [(eid, entities[eid].name) for eid in sorted_ids if eid in entities]

    def unreachable_page_ids(self, entity_ids: set[str]) -> set[str]:
        unreachable: set[str] = set()
        for eid in entity_ids:
            outgoing = self._store.graph.get_outgoing(eid, NAV)
            backlinks = self._store.graph.get_incoming(eid, LINK)
            has_child = any(
                self._store.graph.get_edge_type(eid, t, NAV) == "child"
                for t in outgoing
            )
            has_parent = any(
                self._store.graph.get_edge_type(eid, t, NAV) == "parent"
                for t in outgoing
            )
            if not has_parent and not has_child and not backlinks:
                unreachable.add(eid)
        return unreachable
