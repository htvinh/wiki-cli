"""
store.py

Persistence layer: Store ABC (facade over 5 repos), SQLiteStore, and
ContentRepository (filesystem-backed body storage).
"""

import hashlib
import logging
import os
import sqlite3
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# ── deterministic UUID5 ──────────────────────────────────────────────

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://wiki-compiler/entities")


def make_entity_id(source_path: str) -> str:
    return uuid.uuid5(_NAMESPACE, source_path).hex


# ── version constants for cache invalidation ─────────────────────────

CURRENT_COMPILER_VERSION = "1.0.0"
CURRENT_EXTRACTOR_VERSION = "1.0.0"
CURRENT_TOKENIZER_VERSION = "1.0.0"

SCHEMA_VERSION = 2

# ── helpers ───────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Repository ABCs ──────────────────────────────────────────────────

class EntityRepo(ABC):
    @abstractmethod
    def put(self, entity_id: str, name: str, slug: str, *,
            aliases: str = "", created: str = "",
            source_path: str = "", body_hash: str = "",
            metadata_hash: str = "", source_hash: str = "",
            mtime: float = 0.0, size: int = 0) -> None: ...

    @abstractmethod
    def get(self, entity_id: str) -> dict | None: ...

    @abstractmethod
    def iter_entities(self) -> Generator[dict, None, None]: ...

    @abstractmethod
    def iter_ids(self) -> Generator[str, None, None]: ...

    @abstractmethod
    def exists(self, entity_id: str) -> bool: ...

    @abstractmethod
    def delete(self, entity_id: str) -> None: ...


class GraphRepo(ABC):
    @abstractmethod
    def put_edge(self, source: str, target: str,
                 edge_type: str = "explicit") -> None: ...

    @abstractmethod
    def delete_outgoing(self, entity_id: str) -> None: ...

    @abstractmethod
    def delete_incoming(self, entity_id: str) -> None: ...

    @abstractmethod
    def get_outgoing(self, entity_id: str) -> set[str]: ...

    @abstractmethod
    def get_incoming(self, entity_id: str) -> set[str]: ...

    @abstractmethod
    def iter_edges(self) -> Generator[tuple[str, str], None, None]: ...

    @abstractmethod
    def get_edge_count(self) -> int: ...

    @abstractmethod
    def get_all_outgoing(self) -> dict[str, set[str]]: ...

    @abstractmethod
    def get_outgoing_by_type(self, entity_id: str,
                             edge_type: str) -> set[str]: ...

    @abstractmethod
    def get_incoming_by_type(self, entity_id: str,
                             edge_type: str) -> set[str]: ...

    @abstractmethod
    def iter_edges_by_type(self, edge_type: str) -> Generator[tuple[str, str], None, None]: ...


class IndexRepo(ABC):
    @abstractmethod
    def index_name(self, entity_id: str, name: str) -> None: ...

    @abstractmethod
    def index_alias(self, entity_id: str, alias: str) -> None: ...

    @abstractmethod
    def drop_entity_index(self, entity_id: str) -> None: ...

    @abstractmethod
    def get_candidates(self, word: str) -> list[str]: ...


class StateRepo(ABC):
    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> str | None: ...

    def get_int(self, key: str) -> int | None:
        v = self.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    def get_float(self, key: str) -> float | None:
        v = self.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


class ContentRepository(ABC):
    @abstractmethod
    def put(self, entity_id: str, body: str) -> None: ...

    @abstractmethod
    def get(self, entity_id: str) -> str | None: ...

    @abstractmethod
    def delete(self, entity_id: str) -> None: ...

    @abstractmethod
    def size(self) -> int: ...


# ── Store facade ─────────────────────────────────────────────────────

class Store(ABC):
    @property
    @abstractmethod
    def entities(self) -> EntityRepo: ...

    @property
    @abstractmethod
    def graph(self) -> GraphRepo: ...

    @property
    @abstractmethod
    def index(self) -> IndexRepo: ...

    @property
    @abstractmethod
    def state(self) -> StateRepo: ...

    @property
    @abstractmethod
    def content(self) -> ContentRepository: ...

    @abstractmethod
    @contextmanager
    def transaction(self) -> Generator[None, None, None]: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def vacuum(self) -> None: ...


# ── Schema / Migration ───────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;
PRAGMA cache_size = -64000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS compile_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS entities (
    id                TEXT PRIMARY KEY,
    slug              TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    aliases           TEXT DEFAULT '',
    created           TEXT DEFAULT '',
    source_path       TEXT DEFAULT '',
    source_hash       TEXT DEFAULT '',
    body_hash         TEXT DEFAULT '',
    metadata_hash     TEXT DEFAULT '',
    mtime             REAL DEFAULT 0,
    size              INTEGER DEFAULT 0,
    compiler_version  TEXT DEFAULT '',
    extractor_version TEXT DEFAULT '',
    tokenizer_version TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS graph_edges (
    source    TEXT NOT NULL,
    target    TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'explicit',
    PRIMARY KEY (source, target, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_graph_target ON graph_edges(target);

CREATE TABLE IF NOT EXISTS aliases (
    entity_id TEXT NOT NULL,
    alias     TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias)
);

CREATE TABLE IF NOT EXISTS word_index (
    word               TEXT NOT NULL,
    entity_id          TEXT NOT NULL,
    frequency          INTEGER DEFAULT 1,
    document_frequency INTEGER DEFAULT 1,
    PRIMARY KEY (word, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_word ON word_index(word);
"""


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ── SQLite implementations ──────────────────────────────────────────

class SQLiteEntityRepo(EntityRepo):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def put(self, entity_id: str, name: str, slug: str, *,
            aliases: str = "", created: str = "",
            source_path: str = "", body_hash: str = "",
            metadata_hash: str = "", source_hash: str = "",
            mtime: float = 0.0, size: int = 0) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO entities
                (id, slug, name, aliases, created,
                 source_path, source_hash, body_hash, metadata_hash,
                 mtime, size,
                 compiler_version, extractor_version, tokenizer_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?)
        """, (entity_id, slug, name, aliases, created,
              source_path, source_hash, body_hash, metadata_hash,
              mtime, size,
              CURRENT_COMPILER_VERSION,
              CURRENT_EXTRACTOR_VERSION,
              CURRENT_TOKENIZER_VERSION))

    def get(self, entity_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def iter_entities(self) -> Generator[dict, None, None]:
        cursor = self._conn.execute("SELECT * FROM entities")
        for row in cursor:
            yield dict(row)

    def iter_ids(self) -> Generator[str, None, None]:
        cursor = self._conn.execute("SELECT id FROM entities")
        for row in cursor:
            yield row[0]

    def exists(self, entity_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        return row is not None

    def delete(self, entity_id: str) -> None:
        self._conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))


class SQLiteGraphRepo(GraphRepo):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def put_edge(self, source: str, target: str,
                 edge_type: str = "explicit") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO graph_edges (source, target, edge_type) VALUES (?, ?, ?)",
            (source, target, edge_type),
        )

    def delete_outgoing(self, entity_id: str) -> None:
        self._conn.execute(
            "DELETE FROM graph_edges WHERE source = ?", (entity_id,)
        )

    def delete_incoming(self, entity_id: str) -> None:
        self._conn.execute(
            "DELETE FROM graph_edges WHERE target = ?", (entity_id,)
        )

    def get_outgoing(self, entity_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT target FROM graph_edges WHERE source = ?", (entity_id,)
        ).fetchall()
        return {r[0] for r in rows}

    def get_incoming(self, entity_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT source FROM graph_edges WHERE target = ?", (entity_id,)
        ).fetchall()
        return {r[0] for r in rows}

    def iter_edges(self) -> Generator[tuple[str, str], None, None]:
        cursor = self._conn.execute("SELECT source, target FROM graph_edges")
        for row in cursor:
            yield (row[0], row[1])

    def get_edge_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM graph_edges"
        ).fetchone()
        return row[0] if row else 0

    def get_all_outgoing(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for source, target in self.iter_edges():
            result.setdefault(source, set()).add(target)
        return result

    def get_outgoing_by_type(self, entity_id: str,
                             edge_type: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT target FROM graph_edges WHERE source = ? AND edge_type = ?",
            (entity_id, edge_type),
        ).fetchall()
        return {r[0] for r in rows}

    def get_incoming_by_type(self, entity_id: str,
                             edge_type: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT source FROM graph_edges WHERE target = ? AND edge_type = ?",
            (entity_id, edge_type),
        ).fetchall()
        return {r[0] for r in rows}

    def iter_edges_by_type(self, edge_type: str) -> Generator[tuple[str, str], None, None]:
        cursor = self._conn.execute(
            "SELECT source, target FROM graph_edges WHERE edge_type = ?",
            (edge_type,),
        )
        for row in cursor:
            yield (row[0], row[1])


class SQLiteIndexRepo(IndexRepo):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def index_name(self, entity_id: str, name: str) -> None:
        words = set(name.lower().split())
        for word in words:
            self._conn.execute("""
                INSERT INTO word_index (word, entity_id, frequency, document_frequency)
                VALUES (?, ?, 1, 1)
                ON CONFLICT(word, entity_id) DO UPDATE SET frequency = frequency + 1
            """, (word, entity_id))

    def index_alias(self, entity_id: str, alias: str) -> None:
        words = set(alias.lower().split())
        for word in words:
            self._conn.execute("""
                INSERT INTO word_index (word, entity_id, frequency, document_frequency)
                VALUES (?, ?, 1, 1)
                ON CONFLICT(word, entity_id) DO UPDATE SET frequency = frequency + 1
            """, (word, entity_id))

    def drop_entity_index(self, entity_id: str) -> None:
        self._conn.execute(
            "DELETE FROM word_index WHERE entity_id = ?", (entity_id,)
        )

    def get_candidates(self, word: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT entity_id FROM word_index WHERE word = ?", (word.lower(),)
        ).fetchall()
        return [r[0] for r in rows]


class SQLiteStateRepo(StateRepo):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO compile_state (key, value) VALUES (?, ?)",
            (key, value),
        )

    def get(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM compile_state WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None


class FilesystemContentRepository(ContentRepository):
    def __init__(self, cache_dir: str):
        self._root = os.path.join(cache_dir, "content")
        os.makedirs(self._root, exist_ok=True)

    def _path(self, entity_id: str) -> str:
        return os.path.join(self._root, f"{entity_id}.txt")

    def put(self, entity_id: str, body: str) -> None:
        path = self._path(entity_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    def get(self, entity_id: str) -> str | None:
        path = self._path(entity_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def delete(self, entity_id: str) -> None:
        path = self._path(entity_id)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def size(self) -> int:
        total = 0
        for fname in os.listdir(self._root):
            if fname.endswith(".txt"):
                total += os.path.getsize(os.path.join(self._root, fname))
        return total


# ── SQLiteStore ──────────────────────────────────────────────────────

class SQLiteStore(Store):
    def __init__(self, db_path: str, cache_dir: str | None = None):
        self._db_path = db_path
        self._cache_dir = cache_dir or os.path.join(os.path.dirname(db_path))
        self._conn: sqlite3.Connection | None = None
        self._entity_repo: SQLiteEntityRepo | None = None
        self._graph_repo: SQLiteGraphRepo | None = None
        self._index_repo: SQLiteIndexRepo | None = None
        self._state_repo: SQLiteStateRepo | None = None
        self._content_repo: FilesystemContentRepository | None = None
        self._open()

    def _open(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path, isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._entity_repo = SQLiteEntityRepo(self._conn)
        self._graph_repo = SQLiteGraphRepo(self._conn)
        self._index_repo = SQLiteIndexRepo(self._conn)
        self._state_repo = SQLiteStateRepo(self._conn)
        self._content_repo = FilesystemContentRepository(self._cache_dir)
        _apply_schema(self._conn)
        self._migrate()
        logger.info("Opened store at %s (cache: %s)", self._db_path, self._cache_dir)

    def _migrate(self) -> None:
        assert self._state_repo is not None
        assert self._conn is not None
        stored = self._state_repo.get("schema_version")
        if stored is None:
            self._state_repo.set("schema_version", str(SCHEMA_VERSION))
            self._conn.commit()
        elif int(stored) < SCHEMA_VERSION:
            for v in range(int(stored) + 1, SCHEMA_VERSION + 1):
                logger.info("Applying schema migration v%s", v)
                if v == 2:
                    self._conn.executescript(
                        "ALTER TABLE graph_edges ADD COLUMN "
                        "edge_type TEXT NOT NULL DEFAULT 'explicit';\n"
                        "CREATE TABLE IF NOT EXISTS graph_edges_v2 (\n"
                        "    source    TEXT NOT NULL,\n"
                        "    target    TEXT NOT NULL,\n"
                        "    edge_type TEXT NOT NULL DEFAULT 'explicit',\n"
                        "    PRIMARY KEY (source, target, edge_type)\n"
                        ");\n"
                        "INSERT INTO graph_edges_v2 (source, target, edge_type)\n"
                        "SELECT source, target, edge_type FROM graph_edges;\n"
                        "DROP TABLE graph_edges;\n"
                        "ALTER TABLE graph_edges_v2 RENAME TO graph_edges;\n"
                        "CREATE INDEX IF NOT EXISTS idx_graph_target "
                        "ON graph_edges(target);\n"
                    )
            self._state_repo.set("schema_version", str(SCHEMA_VERSION))
            self._conn.commit()

    @property
    def entities(self) -> EntityRepo:
        assert self._entity_repo is not None
        return self._entity_repo

    @property
    def graph(self) -> GraphRepo:
        assert self._graph_repo is not None
        return self._graph_repo

    @property
    def index(self) -> IndexRepo:
        assert self._index_repo is not None
        return self._index_repo

    @property
    def state(self) -> StateRepo:
        assert self._state_repo is not None
        return self._state_repo

    @property
    def content(self) -> ContentRepository:
        assert self._content_repo is not None
        return self._content_repo

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        assert self._conn is not None
        self._conn.execute("BEGIN")
        try:
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def vacuum(self) -> None:
        assert self._conn is not None
        self._conn.execute("VACUUM")


# ── MemoryStore (testing) ────────────────────────────────────────────

class _MemoryEntityRepo(EntityRepo):
    def __init__(self):
        self._data: dict[str, dict] = {}

    def put(self, entity_id: str, name: str, slug: str, *,
            aliases: str = "", created: str = "",
            source_path: str = "", body_hash: str = "",
            metadata_hash: str = "", source_hash: str = "",
            mtime: float = 0.0, size: int = 0,
            compiler_version: str = CURRENT_COMPILER_VERSION,
            extractor_version: str = CURRENT_EXTRACTOR_VERSION,
            tokenizer_version: str = CURRENT_TOKENIZER_VERSION) -> None:
        self._data[entity_id] = {
            "id": entity_id, "slug": slug, "name": name,
            "aliases": aliases, "created": created,
            "source_path": source_path, "body_hash": body_hash,
            "metadata_hash": metadata_hash, "source_hash": source_hash,
            "mtime": mtime, "size": size,
            "compiler_version": compiler_version,
            "extractor_version": extractor_version,
            "tokenizer_version": tokenizer_version,
        }

    def get(self, entity_id: str) -> dict | None:
        return self._data.get(entity_id)

    def iter_entities(self) -> Generator[dict, None, None]:
        for v in self._data.values():
            yield v

    def iter_ids(self) -> Generator[str, None, None]:
        yield from self._data

    def exists(self, entity_id: str) -> bool:
        return entity_id in self._data

    def delete(self, entity_id: str) -> None:
        self._data.pop(entity_id, None)


class _MemoryGraphRepo(GraphRepo):
    def __init__(self):
        self._edges: dict[tuple[str, str], str] = {}  # (source, target) -> edge_type

    def put_edge(self, source: str, target: str,
                 edge_type: str = "explicit") -> None:
        self._edges[(source, target)] = edge_type

    def delete_outgoing(self, entity_id: str) -> None:
        for key in list(self._edges):
            s, t = key
            if s == entity_id:
                del self._edges[key]

    def delete_incoming(self, entity_id: str) -> None:
        for key in list(self._edges):
            s, t = key
            if t == entity_id:
                del self._edges[key]

    def get_outgoing(self, entity_id: str) -> set[str]:
        return {t for (s, t) in self._edges if s == entity_id}

    def get_incoming(self, entity_id: str) -> set[str]:
        return {s for (s, t) in self._edges if t == entity_id}

    def iter_edges(self) -> Generator[tuple[str, str], None, None]:
        for s, t in self._edges:
            yield (s, t)

    def get_edge_count(self) -> int:
        return len(self._edges)

    def get_all_outgoing(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for s, t in self._edges:
            result.setdefault(s, set()).add(t)
        return result

    def get_outgoing_by_type(self, entity_id: str,
                             edge_type: str) -> set[str]:
        return {t for (s, t), et in self._edges.items()
                if s == entity_id and et == edge_type}

    def get_incoming_by_type(self, entity_id: str,
                             edge_type: str) -> set[str]:
        return {s for (s, t), et in self._edges.items()
                if t == entity_id and et == edge_type}

    def iter_edges_by_type(self, edge_type: str) -> Generator[tuple[str, str], None, None]:
        for (s, t), et in self._edges.items():
            if et == edge_type:
                yield (s, t)


class _MemoryIndexRepo(IndexRepo):
    def __init__(self):
        self._index: dict[str, set[str]] = {}

    def index_name(self, entity_id: str, name: str) -> None:
        for word in set(name.lower().split()):
            self._index.setdefault(word, set()).add(entity_id)

    def index_alias(self, entity_id: str, alias: str) -> None:
        for word in set(alias.lower().split()):
            self._index.setdefault(word, set()).add(entity_id)

    def drop_entity_index(self, entity_id: str) -> None:
        for word_set in self._index.values():
            word_set.discard(entity_id)

    def get_candidates(self, word: str) -> list[str]:
        return list(self._index.get(word.lower(), set()))


class _MemoryStateRepo(StateRepo):
    def __init__(self):
        self._data: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def get(self, key: str) -> str | None:
        return self._data.get(key)


class MemoryStore(Store):
    def __init__(self):
        self._entity_repo = _MemoryEntityRepo()
        self._graph_repo = _MemoryGraphRepo()
        self._index_repo = _MemoryIndexRepo()
        self._state_repo = _MemoryStateRepo()
        self._content_repo: ContentRepository | None = None

    @property
    def entities(self) -> EntityRepo:
        return self._entity_repo

    @property
    def graph(self) -> GraphRepo:
        return self._graph_repo

    @property
    def index(self) -> IndexRepo:
        return self._index_repo

    @property
    def state(self) -> StateRepo:
        return self._state_repo

    @property
    def content(self) -> ContentRepository:
        if self._content_repo is None:
            self._content_repo = _MemoryContentRepo()
        return self._content_repo

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        yield

    def close(self) -> None:
        pass

    def vacuum(self) -> None:
        pass


class _MemoryContentRepo(ContentRepository):
    def __init__(self):
        self._data: dict[str, str] = {}

    def put(self, entity_id: str, body: str) -> None:
        self._data[entity_id] = body

    def get(self, entity_id: str) -> str | None:
        return self._data.get(entity_id)

    def delete(self, entity_id: str) -> None:
        self._data.pop(entity_id, None)

    def size(self) -> int:
        return sum(len(v) for v in self._data.values())
