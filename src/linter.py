"""
linter.py

Stage 4: walks the compiled output directory and checks for
broken references and lexically unlinked pages.
"""

import logging
import os
import re
from dataclasses import dataclass, field

from exceptions import LintError

logger = logging.getLogger(__name__)

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\.md\)")
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
    lexical_unlinked_pages: list = field(default_factory=list)

    def is_clean(self) -> bool:
        return not self.broken_links and not self.lexical_unlinked_pages


def lint(output_dir: str) -> LintReport:
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
    slug_to_path: dict[str, str] = {}
    for fname in files:
        slug = os.path.splitext(os.path.basename(fname))[0]
        if slug != "index" and slug not in slug_to_path:
            slug_to_path[slug] = fname
    incoming_count: dict = {slug: 0 for slug in slug_to_path}

    for fname in files:
        path = os.path.join(output_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            raise LintError(f"Cannot read {path}: {e}") from e

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

        related_text = _extract_section(text, "Related")
        for match in LINK_RE.finditer(related_text):
            target = match.group(2)
            if "/" not in target and target in incoming_count:
                incoming_count[target] += 1

    for slug, count in incoming_count.items():
        if count == 0:
            report.lexical_unlinked_pages.append(slug_to_path[slug])

    report.lexical_unlinked_pages.sort()
    logger.info(
        "Linted %d pages: %d broken links, %d lexically unlinked",
        report.total_pages,
        len(report.broken_links),
        len(report.lexical_unlinked_pages),
    )
    return report


def print_report(report: LintReport) -> None:
    print(f"Linted {report.total_pages} pages.")
    if report.broken_links:
        print(f"  {len(report.broken_links)} broken link(s):")
        for source, target in report.broken_links:
            print(f"    {source} -> [{target}] (target not found)")
    else:
        print("  0 broken links.")

    if report.lexical_unlinked_pages:
        print(f"  {len(report.lexical_unlinked_pages)} lexically unlinked page(s):")
        for name in report.lexical_unlinked_pages:
            print(f"    {name}")
        print()
        print("  Lexically unlinked pages are not referenced by exact page title.")
        print("  They may still be semantically related or reachable through navigation.")
    else:
        print("  0 lexically unlinked pages.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = lint("compiled_wiki")
    print_report(r)
