"""
watcher.py

Polling-based file watcher for the wiki compiler. Calls compiler.compile()
on every detected change in the raw notes directory. stdlib-only.
"""

import logging
import os
import time
from typing import Generator

from compiler import CompileEvent, Compiler

logger = logging.getLogger(__name__)


def watch(
    compiler: Compiler,
    raw_dir: str,
    output_dir: str,
    poll_interval: float = 1.0,
    max_cycles: int | None = None,
) -> Generator[CompileEvent, None, None]:
    known: dict[str, tuple[float, int]] = {}

    for doc_path in _scan_txt(raw_dir):
        st = os.stat(doc_path)
        known[doc_path] = (st.st_mtime, round(st.st_size))

    cycles = 0
    yield CompileEvent("watch_start", "watch", time.time())
    for event in compiler.compile_events(raw_dir, output_dir):
        yield event
    cycles += 1

    while True:
        if max_cycles is not None and cycles >= max_cycles:
            return
        time.sleep(poll_interval)
        changed = _detect_changes(raw_dir, known)
        if changed:
            yield CompileEvent("watch_recompile", "watch", time.time(),
                               payload={"changed": sorted(changed)})
            for event in compiler.compile_events(raw_dir, output_dir):
                yield event
            _update_known(raw_dir, known)
            cycles += 1


def _scan_txt(raw_dir: str) -> list[str]:
    if not os.path.isdir(raw_dir):
        return []
    return sorted(
        os.path.join(raw_dir, f) for f in os.listdir(raw_dir)
        if f.endswith(".txt")
    )


def _detect_changes(raw_dir: str,
                    known: dict[str, tuple[float, int]]) -> set[str]:
    changed: set[str] = set()
    current = _scan_txt(raw_dir)

    for doc_path in current:
        st = os.stat(doc_path)
        old = known.get(doc_path)
        if old is None or (st.st_mtime, round(st.st_size)) != old:
            changed.add(doc_path)

    for doc_path in known:
        if doc_path not in current:
            changed.add(doc_path)

    return changed


def _update_known(raw_dir: str,
                  known: dict[str, tuple[float, int]]) -> None:
    current = set(_scan_txt(raw_dir))
    for doc_path in current:
        st = os.stat(doc_path)
        known[doc_path] = (st.st_mtime, round(st.st_size))
    for path in list(known):
        if path not in current:
            del known[path]
