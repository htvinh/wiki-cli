"""
init.py

Zero-configuration entry point. Generates a synthetic corpus and compiles it.
Paths are resolved relative to the project root, not __file__.
"""

import logging
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

from compiler import compile_wiki
from generator import generate_corpus
from linter import print_report

RAW_DIR = os.path.join(PROJECT_DIR, "raw_notes")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "compiled_wiki")
NUM_FILES = 20
SEED = 42


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    if not os.path.isdir(RAW_DIR) or not os.listdir(RAW_DIR):
        print(f"No raw notes found -- generating {NUM_FILES} synthetic files...")
        generate_corpus(RAW_DIR, num_files=NUM_FILES, seed=SEED)
        print(f"Wrote raw notes to {RAW_DIR}")
    else:
        print(f"Using existing raw notes in {RAW_DIR}")

    result = compile_wiki(RAW_DIR, OUTPUT_DIR)
    print(f"\nCompiled {len(result['written_paths'])} pages -> {OUTPUT_DIR}\n")
    print_report(result["lint_report"])


if __name__ == "__main__":
    main()
