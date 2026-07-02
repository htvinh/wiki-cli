"""
graph.py

Stage 2 of the compiler: given the extracted entities, detects mentions of
one entity's name inside another entity's body text and builds a bidirectional
relationship map. Plain dictionaries, no external graph library.

Detection is whole-word, case-insensitive substring matching against known
entity names -- deterministic and dependency-free. This is a lexical match,
not a semantic one: see the "Where This Breaks" section of the article for
what that trade-off costs.
"""

import re


_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _build_phrase_index(entities: dict) -> dict:
    """
    Maps first-word (lowercased) -> list of (word-tuple, entity_id),
    longest word-tuple first, so multi-word names are checked before
    shorter ones that share a first word.
    """
    index = {}
    for eid, ent in entities.items():
        words = tuple(w.lower() for w in _WORD_RE.findall(ent.name))
        if not words:
            continue
        index.setdefault(words[0], []).append((words, eid))

    for first_word in index:
        index[first_word].sort(key=lambda pair: -len(pair[0]))

    return index


def build_graph(entities: dict) -> dict:
    """
    entities: {entity_id: Entity}
    Returns {entity_id: {"outgoing": set(entity_id), "incoming": set(entity_id)}}

    Implementation note: mention detection uses a word-indexed phrase
    matcher rather than a regex per entity (or one giant regex
    alternation). Each body is tokenized once; at each token position we
    only check the small number of entity names that start with that
    word, via a dict lookup, instead of testing every entity name against
    every position. That keeps the stage's cost proportional to total
    corpus size rather than the number of entities, which matters once
    the entity count moves from the dozens into the thousands.
    """
    graph = {eid: {"outgoing": set(), "incoming": set()} for eid in entities}

    if not entities:
        return graph

    phrase_index = _build_phrase_index(entities)

    for eid, ent in entities.items():
        tokens = [w.lower() for w in _WORD_RE.findall(ent.body)]
        seen_targets = set()
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

    return graph


def orphan_ids(graph: dict) -> list:
    """Entities with zero incoming links -- nothing else references them."""
    return sorted(
        eid for eid, edges in graph.items()
        if not edges["incoming"]
    )


if __name__ == "__main__":
    from extractor import extract_all

    ents = extract_all("raw_notes")
    g = build_graph(ents)
    total_edges = sum(len(v["outgoing"]) for v in g.values())
    print(f"Entities: {len(ents)}, directed edges: {total_edges}")
    print(f"Orphans: {orphan_ids(g)}")
