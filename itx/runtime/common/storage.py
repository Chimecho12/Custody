"""Process ownership and serialized, protected SQLite persistence."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from itx.crypto import canonical_json, content_hash_hex

from .primitives import json_loads
from .protection import seal, unseal


class ProcessLock:
    """OS-owned lock: automatically released even when the process is killed."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a+b")  # noqa: SIM115 — 잠금은 객체 수명 동안 열려 있어야 한다 (close 는 release 에서)
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("같은 데이터 폴더를 사용하는 itx 프로세스가 실행 중입니다.") from None

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Store:
    """Single-process serialized SQLite writes; sensitive payloads are OS protected."""
    def __init__(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path / "state.sqlite", check_same_thread=False)
        if os.name != "nt":
            os.chmod(path / "state.sqlite", 0o600)
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, value BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, hash TEXT UNIQUE, value BLOB NOT NULL);
        """)

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json_loads(unseal(row[0])) if row else default

    def put(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, seal(canonical_json(value))))

    def claim(self, key, value):
        with self.lock, self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO kv VALUES (?,?)", (key, seal(canonical_json(value))))
            return cur.rowcount == 1

    def items(self, prefix):
        with self.lock:
            rows = self.db.execute("SELECT key,value FROM kv WHERE key LIKE ? ORDER BY key DESC", (prefix + "%",)).fetchall()
            return [(k, json_loads(unseal(v))) for k, v in rows]

    def count(self, prefix):
        with self.lock:
            return self.db.execute("SELECT count(*) FROM kv WHERE key LIKE ?", (prefix + "%",)).fetchone()[0]

    def enqueue(self, item, capacity=256):
        ident = content_hash_hex(canonical_json(item))
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM outbox WHERE id=?", (ident,)).fetchone():
                return
            if self.db.execute("SELECT count(*) FROM outbox").fetchone()[0] >= capacity:
                raise RuntimeError("증거 큐가 가득 찼습니다. 새 요청을 보류합니다.")
            self.db.execute("INSERT INTO outbox VALUES (?,?)", (ident, seal(canonical_json(item))))

    def pending(self):
        with self.lock:
            return [(i, json_loads(unseal(v))) for i, v in self.db.execute("SELECT id,value FROM outbox ORDER BY rowid")]

    def ack(self, ident):
        with self.lock, self.db:
            self.db.execute("DELETE FROM outbox WHERE id=?", (ident,))

    def close(self):
        self.db.close()
