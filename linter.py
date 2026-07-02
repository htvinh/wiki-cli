"""
linter.py

Stage 4 of the compiler: walks the compiled output directory and checks
its own work. No LLM-as-a-judge -- just deterministic structural checks:

  - broken references: a [[Link]] that points to a page not present
    in the compiled set
  - orphan pages: pages with zero incoming references (also surfaced
    by graph.py, re-checked here against the actual written files as
    a belt-and-suspenders validation step)

Returns a structured report; also usable as a standalone CLI.
"""

import os
import re
from dataclasses import dataclass, field


LINK_RE = re.compile(r"\[\[(.+?)\]\]")
SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _extract_section(text: str, heading: str) -> str:
    """Returns the body text under a given '## Heading', or '' if absent."""
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
    broken_links: list = field(default_factory=list)   # (source_file, broken_target_name)
    orphan_pages: list = field(default_factory=list)    # filenames with no incoming links

    def is_clean(self) -> bool:
        return not self.broken_links and not self.orphan_pages


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def lint(output_dir: str) -> LintReport:
    report = LintReport()
    files = sorted(f for f in os.listdir(output_dir) if f.endswith(".md"))
    report.total_pages = len(files)

    known_slugs = {os.path.splitext(f)[0] for f in files}
    incoming_count = {slug: 0 for slug in known_slugs}

    for fname in files:
        path = os.path.join(output_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        # Broken-link check: any [[link]] anywhere in the file must resolve
        # to a known page, regardless of which section it's in.
        for match in LINK_RE.finditer(text):
            target_name = match.group(1)
            target_slug = _slugify(target_name)
            if target_slug not in known_slugs:
                report.broken_links.append((fname, target_name))

        # Incoming-link count for orphan detection: only count links from
        # the "Related" section (true outgoing edges). The "Referenced By"
        # section also contains [[links]], but those name pages that link
        # TO this one -- counting them here would double back on itself
        # and make every page falsely look non-orphaned.
        related_text = _extract_section(text, "Related")
        for match in LINK_RE.finditer(related_text):
            target_slug = _slugify(match.group(1))
            if target_slug in incoming_count:
                incoming_count[target_slug] += 1

    for slug, count in incoming_count.items():
        if count == 0:
            report.orphan_pages.append(f"{slug}.md")

    report.orphan_pages.sort()
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
    r = lint("compiled_wiki")
    print_report(r)
