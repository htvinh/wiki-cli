"""
init.py

Zero-configuration entry point. Just hit Run on this file -- no script
parameters, no working directory setup, nothing to configure.

It will:
  1. Generate a synthetic raw_notes/ folder (20 files) if one doesn't
     already exist next to this file.
  2. Compile it into compiled_wiki/.
  3. Print the lint report.

Paths are resolved relative to this file's own location, not PyCharm's
working directory, so it works regardless of Run Configuration settings.
"""

import os
import sys

# Ensure imports work regardless of PyCharm's working directory setting.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from generator import generate_corpus
from compiler import compile_wiki
from linter import print_report

RAW_DIR = os.path.join(THIS_DIR, "raw_notes")
OUTPUT_DIR = os.path.join(THIS_DIR, "compiled_wiki")
NUM_FILES = 20
SEED = 42


def main():
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
