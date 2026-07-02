"""
rewriter.py

Stage 3 of the compiler: writes each entity out as a markdown wiki page.

This is deliberately NOT framed as an AST operation. It is targeted string
replacement between recognized '## Heading' boundaries. Two kinds of
sections exist in a compiled page:

  - Compiler-owned sections (## Metadata, ## Related): fully regenerated
    on every compile from the current entities/graph, so they are always
    in sync with the source.
  - Human-owned sections (## Notes): if the page already exists on disk
    and has a ## Notes section, its content is preserved across recompiles
    instead of being overwritten. If no ## Notes section exists yet, an
    empty placeholder is created.

This gives the "compile from source of truth, but don't destroy what a
person typed by hand" behavior without pretending to be a general-purpose
AST/tree parser.
"""

import os
import re


SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _parse_existing_sections(text: str) -> dict:
    """
    Splits an existing compiled markdown file into {heading: body_text}.
    Body text for a heading runs until the next '## ' heading or EOF.
    """
    sections = {}
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[heading] = text[start:end].strip("\n")
    return sections


def render_page(entity, graph_edges: dict, entities: dict, existing_path: str = None) -> str:
    """
    entity: Entity
    graph_edges: {"outgoing": set(entity_id), "incoming": set(entity_id)}
    entities: full {entity_id: Entity} map, needed to resolve link display names
    existing_path: path to a previously compiled page, if one exists, so its
                    human-owned ## Notes section can be preserved.
    """
    preserved_notes = ""
    if existing_path and os.path.exists(existing_path):
        with open(existing_path, "r", encoding="utf-8") as f:
            old_text = f.read()
        old_sections = _parse_existing_sections(old_text)
        preserved_notes = old_sections.get("Notes", "").strip()

    lines = [f"# {entity.name}", ""]

    # --- Compiler-owned: Metadata ---
    lines.append("## Metadata")
    lines.append(f"- created: {entity.created or 'unknown'}")
    lines.append(f"- aliases: {', '.join(entity.aliases) if entity.aliases else 'none'}")
    lines.append(f"- source: {entity.source_path}")
    lines.append("")

    # --- Compiler-owned: Related (from the graph) ---
    lines.append("## Related")
    outgoing = sorted(graph_edges["outgoing"])
    if outgoing:
        for target_id in outgoing:
            target_name = entities[target_id].name
            lines.append(f"- [[{target_name}]]")
    else:
        lines.append("- (no outgoing references found)")
    lines.append("")

    # --- Compiler-owned: Referenced By ---
    lines.append("## Referenced By")
    incoming = sorted(graph_edges["incoming"])
    if incoming:
        for source_id in incoming:
            source_name = entities[source_id].name
            lines.append(f"- [[{source_name}]]")
    else:
        lines.append("- (orphan: no other page links here)")
    lines.append("")

    # --- Compiler-owned: Body (raw extracted text) ---
    lines.append("## Body")
    lines.append(entity.body)
    lines.append("")

    # --- Human-owned: Notes (preserved across recompiles) ---
    lines.append("## Notes")
    lines.append(preserved_notes if preserved_notes else "_(add your own notes here -- preserved on recompile)_")
    lines.append("")

    return "\n".join(lines)


def compile_pages(entities: dict, graph: dict, output_dir: str) -> list:
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for eid, entity in entities.items():
        out_path = os.path.join(output_dir, f"{eid}.md")
        content = render_page(entity, graph[eid], entities, existing_path=out_path)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        written.append(out_path)
    return written


if __name__ == "__main__":
    from extractor import extract_all
    from graph import build_graph

    ents = extract_all("raw_notes")
    g = build_graph(ents)
    paths = compile_pages(ents, g, "compiled_wiki")
    print(f"Compiled {len(paths)} pages to compiled_wiki/")
