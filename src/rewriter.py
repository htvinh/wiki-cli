"""
rewriter.py

Stage 3: writes each entity out as a markdown wiki page.
Compiler-owned sections are fully regenerated; the human-owned ## Notes
section is preserved across recompiles.
Uses optional multi-graph related/backlink functions from RelationshipEngine.
"""

import html
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


def render_page(entity, graph_edges: dict, entities: dict,
                existing_path: str | None = None,
                compute_related_fn=None,
                compute_backlinks_fn=None,
                entities_for_related: dict | None = None,
                raw_dir: str = "") -> str:
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
    if raw_dir and entity.source_path.startswith(raw_dir):
        rel_source = os.path.relpath(entity.source_path, raw_dir)
    else:
        rel_source = entity.source_path
    lines.append(f"- source: {rel_source}")
    lines.append("")

    lines.append("## Related")
    ef = entities_for_related or entities
    if compute_related_fn is not None:
        related = compute_related_fn(entity.entity_id, ef)
        if related:
            for _eid, name in related:
                slug = name.lower().replace(" ", "_").replace("-", "_")
                lines.append(f"- [{name}]({slug}.md)")
        else:
            lines.append("- (no related references found)")
    else:
        outgoing = sorted(graph_edges["outgoing"])
        if outgoing:
            for target_id in outgoing:
                target = entities[target_id]
                lines.append(f"- [{target.name}]({target.slug}.md)")
        else:
            lines.append("- (no related references found)")
    lines.append("")

    lines.append("## Linked From")
    if compute_backlinks_fn is not None:
        backlinks = compute_backlinks_fn(entity.entity_id, ef)
        if backlinks:
            for _eid, name in backlinks:
                slug = name.lower().replace(" ", "_").replace("-", "_")
                lines.append(f"- [{name}]({slug}.md)")
        else:
            lines.append("- (no pages link to this page)")
    else:
        incoming = sorted(graph_edges["incoming"])
        if incoming:
            for source_id in incoming:
                source = entities[source_id]
                lines.append(f"- [{source.name}]({source.slug}.md)")
        else:
            lines.append("- (no pages link to this page)")
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
        "Rendered page '%s'", entity.name,
    )
    return content


def _write_index(output_dir: str) -> str | None:
    dir_entries: dict[str, list[str]] = {}
    for root, dirs, files in os.walk(output_dir):
        rel = os.path.normpath(os.path.relpath(root, output_dir))
        dir_entries.setdefault(rel, [])
        dir_entries[rel].extend(
            f for f in files if f.endswith(".md") and f != "index.md"
        )
        for d in dirs:
            dir_entries.setdefault(os.path.normpath(os.path.join(rel, d)), [])

    root_index: str | None = None
    topo = sorted(dir_entries, key=lambda p: p.count(os.sep), reverse=True)
    for rel_path in topo:
        entries = dir_entries[rel_path]
        sub_dirs = sorted(
            d for d in dir_entries
            if d != "." and (
                os.path.dirname(d) == rel_path
                or (rel_path == "." and os.path.dirname(d) == "")
            )
        )
        if not entries and not sub_dirs:
            continue
        lines = ["# Wiki Index", ""]
        for fn in sorted(entries):
            name = os.path.splitext(fn)[0]
            lines.append(f"- [{name}]({fn})")
        for sub in sub_dirs:
            sub_rel = os.path.relpath(sub, rel_path) if rel_path != "." else sub
            lines.append(f"- [{os.path.basename(sub)}]({sub_rel}/index.md)")
        lines.append("")
        idx_dir = output_dir if rel_path == "." else os.path.join(output_dir, rel_path)
        os.makedirs(idx_dir, exist_ok=True)
        idx_path = os.path.join(idx_dir, "index.md")
        try:
            with open(idx_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except OSError as e:
            raise RewriteError(f"Cannot write {idx_path}: {e}")
        if root_index is None and rel_path == ".":
            root_index = idx_path

        html_lines = ["<!DOCTYPE html>",
                      '<html lang="en">',
                      "<head><meta charset='utf-8'>",
                      "<title>Wiki Index</title>",
                      "<style>"
                      "body{font-family:sans-serif;max-width:720px;"
                      "margin:40px auto;padding:0 20px;line-height:1.6}"
                      "a{color:#0366d6;text-decoration:none}"
                      "a:hover{text-decoration:underline}"
                      "ul{list-style:none;padding:0}li{padding:4px 0}"
                      "</style>",
                      "</head><body>",
                      "<h1>Wiki Index</h1><ul>"]
        for fn in sorted(entries):
            name = os.path.splitext(fn)[0]
            display = html.escape(name.replace("_", " ").replace("-", " ").title())
            href = html.escape(fn)
            html_lines.append(f'<li><a href="{href}">{display}</a></li>')
        for sub in sub_dirs:
            sub_rel = os.path.relpath(sub, rel_path) if rel_path != "." else sub
            display = html.escape(
                os.path.basename(sub).replace("_", " ").replace("-", " ").title()
            )
            href = f"{html.escape(sub_rel)}/index.html"
            html_lines.append(f'<li><a href="{href}">{display}/</a></li>')
        html_lines += ["</ul>", "</body></html>"]
        html_path = os.path.join(idx_dir, "index.html")
        try:
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(html_lines))
        except OSError as e:
            raise RewriteError(f"Cannot write {html_path}: {e}")
    return root_index


def compile_pages(entities: dict, graph: dict, output_dir: str,
                  raw_dir: str = "",
                  compute_related_fn=None,
                  compute_backlinks_fn=None,
                  entities_for_related: dict | None = None) -> list:
    os.makedirs(output_dir, exist_ok=True)
    abs_raw = os.path.abspath(raw_dir) if raw_dir else ""
    written = []
    for eid, entity in entities.items():
        fname = f"{entity.slug}.md" if entity.slug else f"{eid}.md"
        if abs_raw and entity.source_path.startswith(abs_raw):
            rel = os.path.relpath(os.path.dirname(entity.source_path), abs_raw)
            subdir = rel if rel != "." else ""
        else:
            subdir = ""
        out_subdir = os.path.join(output_dir, subdir) if subdir else output_dir
        os.makedirs(out_subdir, exist_ok=True)
        out_path = os.path.join(out_subdir, fname)
        content = render_page(entity, graph[eid], entities, existing_path=out_path,
                              compute_related_fn=compute_related_fn,
                              compute_backlinks_fn=compute_backlinks_fn,
                              entities_for_related=entities_for_related,
                              raw_dir=abs_raw)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise RewriteError(f"Cannot write {out_path}: {e}") from e
        written.append(out_path)

    idx_path = _write_index(output_dir)
    if idx_path:
        written.append(idx_path)
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
