"""
__main__.py

Entry point for ``python -m src`` — delegates to the CLI compiler.
"""

import sys

from src.compiler import main

sys.exit(main())
