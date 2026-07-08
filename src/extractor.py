"""
extractor.py

Stage 1: scans raw text files and pulls out structural signal
(entity name, aliases, created date, body text) using regex only.
"""

import logging
import os
import re
from dataclasses import dataclass, field

from exceptions import ExtractionError
from store import make_entity_id

logger = logging.getLogger(__name__)

HEADER_HASH_RE = re.compile(r"^#\s+(.+)$")
CREATED_RE = re.compile(r"^created:\s*(.+)$", re.IGNORECASE)
ALIASES_RE = re.compile(r"^aliases:\s*(.+)$", re.IGNORECASE)


@dataclass
class Entity:
    entity_id: str
    name: str
    slug: str = ""
    aliases: list = field(default_factory=list)
    created: str = ""
    body: str = ""
    source_path: str = ""


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def _derive_name_from_filename(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("_", " ").title()


def extract_entity(path: str, content: str | None = None) -> Entity:
    if content is None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError as e:
            raise ExtractionError(f"Cannot read {path}: {e}") from e
    else:
        lines = content.splitlines()

    name: str | None = None
    aliases: list[str] = []
    created = ""
    body_lines: list[str] = []

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

    entity_id = make_entity_id(os.path.abspath(path))
    slug = _slugify(name)
    body = "\n".join(body_lines).strip()

    entity = Entity(
        entity_id=entity_id,
        name=name,
        slug=slug,
        aliases=aliases,
        created=created,
        body=body,
        source_path=path,
    )
    logger.debug("Extracted entity '%s' from %s", name, path)
    return entity


def extract_all(raw_dir: str) -> dict:
    entities: dict = {}
    try:
        fnames = sorted(os.listdir(raw_dir))
    except OSError as e:
        raise ExtractionError(f"Cannot list directory {raw_dir}: {e}") from e

    for fname in fnames:
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(raw_dir, fname)
        entity = extract_entity(path)
        entities[entity.entity_id] = entity

    logger.info("Extracted %d entities from %s", len(entities), raw_dir)
    return entities


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ents = extract_all("raw_notes")
    print(f"Extracted {len(ents)} entities")
    sample_id = next(iter(ents))
    print(ents[sample_id])
