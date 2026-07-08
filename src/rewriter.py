"""
rewriter.py

Stage 3: writes each entity out as a markdown wiki page.
Compiler-owned sections are fully regenerated; the human-owned ## Notes
section is preserved across recompiles.
"""

import logging
import os
import re

from exceptions import RewriteError

logger = logging.getLogger(__name__)

SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _parse_existing_sections(text: str) -> dict:
    sections = {}
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[heading] = text[start:end].strip("\n")
    return sections


def render_page(entity, graph_edges: dict, entities: dict, existing_path: str | None = None) -> str:
    preserved_notes = ""
    if existing_path and os.path.exists(existing_path):
        try:
            with open(existing_path, "r", encoding="utf-8") as f:
                old_text = f.read()
        except OSError as e:
            raise RewriteError(f"Cannot read existing page {existing_path}: {e}") from e
        old_sections = _parse_existing_sections(old_text)
        preserved_notes = old_sections.get("Notes", "").strip()

    lines = [f"# {entity.name}", ""]

    lines.append("## Metadata")
    lines.append(f"- created: {entity.created or 'unknown'}")
    lines.append(f"- aliases: {', '.join(entity.aliases) if entity.aliases else 'none'}")
    lines.append(f"- source: {entity.source_path}")
    lines.append("")

    lines.append("## Related")
    outgoing = sorted(graph_edges["outgoing"])
    if outgoing:
        for target_id in outgoing:
            target_name = entities[target_id].name
            lines.append(f"- [[{target_name}]]")
    else:
        lines.append("- (no outgoing references found)")
    lines.append("")

    lines.append("## Referenced By")
    incoming = sorted(graph_edges["incoming"])
    if incoming:
        for source_id in incoming:
            source_name = entities[source_id].name
            lines.append(f"- [[{source_name}]]")
    else:
        lines.append("- (orphan: no other page links here)")
    lines.append("")

    lines.append("## Body")
    lines.append(entity.body)
    lines.append("")

    lines.append("## Notes")
    placeholder = "_(add your own notes here -- preserved on recompile)_"
    lines.append(preserved_notes if preserved_notes else placeholder)
    lines.append("")

    content = "\n".join(lines)
    logger.debug(
        "Rendered page '%s' (%s outgoing, %s incoming)",
        entity.name, len(outgoing), len(incoming),
    )
    return content


def compile_pages(entities: dict, graph: dict, output_dir: str) -> list:
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for eid, entity in entities.items():
        fname = f"{entity.slug}.md" if entity.slug else f"{eid}.md"
        out_path = os.path.join(output_dir, fname)
        content = render_page(entity, graph[eid], entities, existing_path=out_path)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise RewriteError(f"Cannot write {out_path}: {e}") from e
        written.append(out_path)

    logger.info("Wrote %d pages to %s", len(written), output_dir)
    return written


if __name__ == "__main__":
    from extractor import extract_all
    from graph import build_graph

    logging.basicConfig(level=logging.INFO)
    ents = extract_all("raw_notes")
    g = build_graph(ents)
    paths = compile_pages(ents, g, "compiled_wiki")
    print(f"Compiled {len(paths)} pages to compiled_wiki/")
