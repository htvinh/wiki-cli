"""
linter.py

Stage 4: walks the compiled output directory and checks for
broken references and orphan pages.
"""

import logging
import os
import re
from dataclasses import dataclass, field

from exceptions import LintError

logger = logging.getLogger(__name__)

LINK_RE = re.compile(r"\[\[(.+?)\]\]")
SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _extract_section(text: str, heading: str) -> str:
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        if m.group(1).strip() == heading:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[start:end]
    return ""


@dataclass
class LintReport:
    total_pages: int = 0
    broken_links: list = field(default_factory=list)
    orphan_pages: list = field(default_factory=list)

    def is_clean(self) -> bool:
        return not self.broken_links and not self.orphan_pages


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def lint(output_dir: str) -> LintReport:
    report = LintReport()

    try:
        files = sorted(f for f in os.listdir(output_dir) if f.endswith(".md"))
    except OSError as e:
        raise LintError(f"Cannot list directory {output_dir}: {e}") from e

    report.total_pages = len(files)
    known_slugs = {os.path.splitext(f)[0] for f in files}
    incoming_count: dict = {slug: 0 for slug in known_slugs}

    for fname in files:
        path = os.path.join(output_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise LintError(f"Cannot read {path}: {e}") from e

        for match in LINK_RE.finditer(text):
            target_name = match.group(1)
            target_slug = _slugify(target_name)
            if target_slug not in known_slugs:
                report.broken_links.append((fname, target_name))

        related_text = _extract_section(text, "Related")
        for match in LINK_RE.finditer(related_text):
            target_slug = _slugify(match.group(1))
            if target_slug in incoming_count:
                incoming_count[target_slug] += 1

    for slug, count in incoming_count.items():
        if count == 0:
            report.orphan_pages.append(f"{slug}.md")

    report.orphan_pages.sort()
    logger.info(
        "Linted %d pages: %d broken links, %d orphans",
        report.total_pages,
        len(report.broken_links),
        len(report.orphan_pages),
    )
    return report


def print_report(report: LintReport) -> None:
    print(f"Linted {report.total_pages} pages.")
    if report.broken_links:
        print(f"  {len(report.broken_links)} broken link(s):")
        for source, target in report.broken_links:
            print(f"    {source} -> [[{target}]] (target not found)")
    else:
        print("  0 broken links.")

    if report.orphan_pages:
        print(f"  {len(report.orphan_pages)} orphan page(s):")
        for name in report.orphan_pages:
            print(f"    {name}")
    else:
        print("  0 orphan pages.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = lint("compiled_wiki")
    print_report(r)
