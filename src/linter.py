"""
linter.py

Stage 4: walks the compiled output directory and checks for:
- broken links
- duplicate titles (content pages only — index/README/Home/Wiki Index exempt)
- unreachable pages (no parent, no child, no backlink, not referenced by an index)
- missing metadata (only reported with --strict; required fields only)
"""

import logging
import os
import re
from dataclasses import dataclass, field

from exceptions import LintError

logger = logging.getLogger(__name__)

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\.md\)")
SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
METADATA_ITEM_RE = re.compile(r"^-\s*(\w+):\s*(.+)$", re.MULTILINE)

# Index pages are exempt from duplicate-title checks
_INDEX_EXEMPT = {"index", "readme", "home", "wiki_index"}


def _slug_from_path(fname: str) -> str:
    return os.path.splitext(os.path.basename(fname))[0]


@dataclass
class LintReport:
    total_pages: int = 0
    content_pages: int = 0
    index_pages: int = 0
    broken_links: list = field(default_factory=list)
    duplicate_titles: list = field(default_factory=list)
    unreachable_pages: list = field(default_factory=list)
    missing_metadata: list = field(default_factory=list)

    def is_clean(self) -> bool:
        return (not self.broken_links
                and not self.duplicate_titles
                and not self.unreachable_pages)


def lint(output_dir: str, store=None, strict: bool = False) -> LintReport:
    report = LintReport()

    try:
        files: list[str] = []
        for root, _dirs, fnames in os.walk(output_dir):
            for f in fnames:
                if f.endswith(".md"):
                    files.append(os.path.relpath(os.path.join(root, f), output_dir))
    except OSError as e:
        raise LintError(f"Cannot list directory {output_dir}: {e}") from e

    files.sort()
    report.total_pages = len(files)

    # Build slug→path map (skip index pages for link resolution)
    slug_to_path: dict[str, str] = {}
    for fname in files:
        slug = _slug_from_path(fname)
        if slug not in slug_to_path:
            slug_to_path[slug] = fname

    # Identify which files are index pages
    index_slugs: set[str] = set()
    for fname in files:
        slug = _slug_from_path(fname)
        if _slug_is_index_page(fname):
            index_slugs.add(slug)

    report.index_pages = len(index_slugs)
    report.content_pages = report.total_pages - report.index_pages

    incoming_count: dict = {slug: 0 for slug in slug_to_path}
    title_counts: dict[str, list[str]] = {}

    for fname in files:
        path = os.path.join(output_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            raise LintError(f"Cannot read {path}: {e}") from e

        is_index = _slug_is_index_page(fname)

        # Check broken links
        for match in LINK_RE.finditer(text):
            target = match.group(2)
            if "/" in target:
                target_path = os.path.normpath(
                    os.path.join(output_dir, os.path.dirname(fname), target + ".md")
                )
                if not os.path.isfile(target_path):
                    report.broken_links.append((fname, match.group(1)))
            elif target not in slug_to_path:
                report.broken_links.append((fname, match.group(1)))

        # Count incoming links from ## Related and every other section
        for match in LINK_RE.finditer(text):
            target = match.group(2)
            if "/" not in target and target in incoming_count:
                incoming_count[target] += 1

        # Track duplicate titles — skip index pages
        if not is_index:
            title_m = TITLE_RE.search(text)
            if title_m:
                title = title_m.group(1).strip()
                title_counts.setdefault(title, []).append(fname)

        # Check missing metadata (only in strict mode)
        if strict:
            metadata_text = _extract_section(text, "Metadata")
            if metadata_text:
                meta_fields = set()
                for mm in METADATA_ITEM_RE.finditer(metadata_text):
                    val = mm.group(2).strip()
                    if val not in ("unknown", "none", ""):
                        meta_fields.add(mm.group(1))
                if "created" not in meta_fields and "created" not in meta_fields:
                    report.missing_metadata.append((fname, "created"))
                if "aliases" not in meta_fields:
                    report.missing_metadata.append((fname, "aliases"))

    # Duplicate titles (content pages only)
    for title, paths in title_counts.items():
        if len(paths) > 1:
            report.duplicate_titles.append((title, paths))

    # Unreachable pages (requires store with relationship data)
    if store is not None:
        from relationship import RelationshipEngine

        engine = RelationshipEngine(store)
        all_ids = set(store.entities.iter_ids())
        unreachable_ids = engine.unreachable_page_ids(all_ids)

        # A page is reachable if it's mentioned in any index page
        reachable_via_index: set[str] = set()
        for fname in files:
            if _slug_from_path(fname) in index_slugs:
                path = os.path.join(output_dir, fname)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    continue
                for match in LINK_RE.finditer(text):
                    target_slug = match.group(2)
                    if target_slug in slug_to_path and target_slug not in index_slugs:
                        for ent in store.entities.iter_entities():
                            if ent.get("slug") == target_slug:
                                reachable_via_index.add(ent["id"])
                                break

        unreachable_ids -= reachable_via_index

        eid_to_path: dict[str, str] = {}
        for ent in store.entities.iter_entities():
            slug = ent.get("slug", "")
            if slug in slug_to_path:
                eid_to_path[ent["id"]] = slug_to_path[slug]
        for eid in unreachable_ids:
            if eid in eid_to_path:
                report.unreachable_pages.append(eid_to_path[eid])
    else:
        # Without store, estimate reachability from incoming links
        for slug, count in incoming_count.items():
            if count == 0 and slug not in index_slugs:
                report.unreachable_pages.append(slug_to_path[slug])

    report.unreachable_pages.sort()

    logger.info(
        "Linted %d pages (%d content, %d index): %d broken, %d duplicate titles, "
        "%d unreachable",
        report.total_pages, report.content_pages, report.index_pages,
        len(report.broken_links),
        len(report.duplicate_titles),
        len(report.unreachable_pages),
    )
    return report


def _extract_section(text: str, heading: str) -> str:
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        if m.group(1).strip() == heading:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[start:end]
    return ""


def _slug_is_index_page(fname: str) -> bool:
    slug = _slug_from_path(fname)
    if slug in _INDEX_EXEMPT:
        return True
    # Pages in subdirectories whose filename is "index" are also index pages
    parts = fname.replace(os.sep, "/").split("/")
    return parts[-1] == "index.md"


def print_report(report: LintReport) -> None:
    print("\nLint Summary")
    print("-" * 28)
    print(f"Pages checked:        {report.total_pages:>3}")
    print(f"Broken links:         {len(report.broken_links):>3}")
    print(f"Duplicate titles:     {len(report.duplicate_titles):>3}")
    print(f"Unreachable pages:    {len(report.unreachable_pages):>3}")

    errors = report.broken_links or report.duplicate_titles
    warnings = report.unreachable_pages

    if not errors and not warnings:
        print("\n✓ All checks passed.")
        return

    if errors:
        print("\nErrors")
        print("-" * 28)
        if report.broken_links:
            print("Broken links:")
            for src, tgt in report.broken_links:
                print(f"  {src} -> [{tgt}] (target not found)")
        if report.duplicate_titles:
            print("Duplicate titles:")
            for title, paths in report.duplicate_titles:
                print(f'  "{title}" in {len(paths)} content pages')
        print()

    if warnings:
        print(f"Unreachable pages ({len(report.unreachable_pages)}):")
        for name in report.unreachable_pages:
            print(f"  • {name}")
        print()

    if errors:
        print("Status: FAILED")
    else:
        print("Status: PASS")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = lint("compiled_wiki")
    print_report(r)
