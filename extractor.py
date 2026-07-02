"""
extractor.py

Stage 1 of the compiler: scans raw text files and pulls out structural
signal (entity name, aliases, created date, body text) using regex only.
No embeddings, no LLM calls. Handles the inconsistent formatting the
generator deliberately produces (header sometimes '#', sometimes bare
uppercase line; metadata sometimes present, sometimes not).
"""

import os
import re
from dataclasses import dataclass, field


HEADER_HASH_RE = re.compile(r"^#\s*(.+)$")
CREATED_RE = re.compile(r"^created:\s*(.+)$", re.IGNORECASE)
ALIASES_RE = re.compile(r"^aliases:\s*(.+)$", re.IGNORECASE)


@dataclass
class Entity:
    entity_id: str          # slug, used as the link/graph key
    name: str                # display name
    aliases: list = field(default_factory=list)
    created: str = ""
    body: str = ""
    source_path: str = ""


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def _derive_name_from_filename(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("_", " ").title()


def extract_entity(path: str) -> Entity:
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    name = None
    aliases = []
    created = ""
    body_lines = []

    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            body_lines.append(raw_line)
            continue

        if name is None:
            m = HEADER_HASH_RE.match(line)
            if m:
                name = m.group(1).strip()
                continue
            # Bare uppercase line heuristic: no lowercase letters present
            # and it's the first non-empty line -> treat as a header.
            if line.isupper() and idx == 0:
                name = line.title()
                continue

        m = CREATED_RE.match(line)
        if m:
            created = m.group(1).strip()
            continue

        m = ALIASES_RE.match(line)
        if m:
            aliases = [a.strip() for a in m.group(1).split(",") if a.strip()]
            continue

        body_lines.append(raw_line)

    if name is None:
        name = _derive_name_from_filename(path)

    entity_id = _slugify(name)
    body = "\n".join(body_lines).strip()

    return Entity(
        entity_id=entity_id,
        name=name,
        aliases=aliases,
        created=created,
        body=body,
        source_path=path,
    )


def extract_all(raw_dir: str) -> dict:
    """
    Returns {entity_id: Entity} for every .txt file in raw_dir.
    """
    entities = {}
    for fname in sorted(os.listdir(raw_dir)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(raw_dir, fname)
        entity = extract_entity(path)
        entities[entity.entity_id] = entity
    return entities


if __name__ == "__main__":
    ents = extract_all("raw_notes")
    print(f"Extracted {len(ents)} entities")
    sample_id = next(iter(ents))
    print(ents[sample_id])
