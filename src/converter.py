"""
converter.py

Document format conversion using MarkItDown. Converts non-txt documents
(.docx, .pdf, .html, .pptx, .xlsx, .csv, .json, .xml, .rtf) to plain
text/markdown so they flow through the wiki pipeline like native .txt files.
"""

import logging
import os

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = frozenset({".txt", ".md"})
CONVERTIBLE_EXTENSIONS = frozenset({
    ".docx", ".pdf", ".html", ".htm",
    ".pptx", ".xlsx", ".csv", ".json", ".xml", ".rtf",
})
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | CONVERTIBLE_EXTENSIONS


def is_supported(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in SUPPORTED_EXTENSIONS


def needs_conversion(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in CONVERTIBLE_EXTENSIONS


def convert_to_text(path: str) -> str:
    from markitdown import MarkItDown
    md = MarkItDown()
    result = md.convert(path)
    return result.text_content
