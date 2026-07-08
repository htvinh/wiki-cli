"""
source.py

SourceProvider abstraction for iterating input documents.
Supports .txt, .md, .docx, .pdf, .html, .pptx, .xlsx, .csv, .json, .xml,
and .rtf via MarkItDown conversion (see converter.py).
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Generator

from converter import needs_conversion

logger = logging.getLogger(__name__)


class Document(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def path(self) -> str: ...

    @property
    @abstractmethod
    def mtime(self) -> float: ...

    @property
    @abstractmethod
    def size(self) -> int: ...

    @abstractmethod
    def read_bytes(self) -> bytes: ...


class SourceProvider(ABC):
    @abstractmethod
    def iter_documents(self, raw_dir: str) -> Generator[Document, None, None]: ...


class FilesystemDocument(Document):
    def __init__(self, path: str):
        self._path = os.path.abspath(path)
        self._stat: os.stat_result | None = None

    @property
    def id(self) -> str:
        return self._path

    @property
    def path(self) -> str:
        return self._path

    @property
    def mtime(self) -> float:
        if self._stat is None:
            self._stat = os.stat(self._path)
        return self._stat.st_mtime

    @property
    def size(self) -> int:
        if self._stat is None:
            self._stat = os.stat(self._path)
        return self._stat.st_size

    def read_bytes(self) -> bytes:
        with open(self._path, "rb") as f:
            return f.read()


class ConvertingDocument(Document):
    """Document backed by a MarkItDown-converted file."""

    def __init__(self, path: str):
        self._path = os.path.abspath(path)
        self._stat: os.stat_result = os.stat(self._path)
        self._content: str | None = None

    @property
    def id(self) -> str:
        return self._path

    @property
    def path(self) -> str:
        return self._path

    @property
    def mtime(self) -> float:
        return self._stat.st_mtime

    @property
    def size(self) -> int:
        return self._stat.st_size

    def read_bytes(self) -> bytes:
        if self._content is None:
            from converter import convert_to_text
            self._content = convert_to_text(self._path)
        return self._content.encode("utf-8")


class FilesystemProvider(SourceProvider):
    def iter_documents(self, raw_dir: str) -> Generator[Document, None, None]:
        try:
            fnames = sorted(os.listdir(raw_dir))
        except OSError as e:
            logger.warning("Cannot list directory %s: %s", raw_dir, e)
            return
        for fname in fnames:
            path = os.path.join(raw_dir, fname)
            if fname.endswith(".txt") or fname.endswith(".md"):
                yield FilesystemDocument(path)
            elif needs_conversion(path):
                yield ConvertingDocument(path)
