"""État privé SQLite : processed, plans, authorizations, digests + verrous exclusifs.

Écritures transactionnelles ; l'autorisation est à usage unique (atomicité garantie
par UPDATE ... WHERE consumed_at IS NULL). Le verrou d'exécution est un lockfile
O_EXCL avec takeover stale = âge ET pid mort (jamais un writer actif).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

# UPDATE...RETURNING exige SQLite >= 3.35 (fail-closed au démarrage).
if tuple(int(p) for p in sqlite3.sqlite_version.split(".")) < (3, 35):
    raise RuntimeError(f"SQLite >= 3.35 requis (trouvé {sqlite3.sqlite_version})")

LOCK_TIMEOUT_SECONDS = 30.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
  mailbox TEXT NOT NULL,
  uidvalidity INTEGER NOT NULL,
  uid INTEGER NOT NULL,
  first_seen TEXT NOT NULL,
  last_action TEXT,
  last_folder TEXT,
  last_ts TEXT,
  PRIMARY KEY (mailbox, uidvalidity, uid)
);
CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS authorizations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_sha TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS digests (
  id TEXT PRIMARY KEY,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  marker TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  post_id TEXT,
  uidvalidity INTEGER,
  markdown TEXT,
  msg_uids TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS digested_msgs (
  mailbox TEXT NOT NULL,
  uidvalidity INTEGER NOT NULL,
  uid INTEGER NOT NULL,
  internaldate TEXT,
  digest_id TEXT NOT NULL,
  PRIMARY KEY (mailbox, uidvalidity, uid, digest_id)
);
CREATE TABLE IF NOT EXISTS plan_results (
  plan_id TEXT NOT NULL,
  uid INTEGER NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  PRIMARY KEY (plan_id, uid)
);
"""


class LockError(Exception):
    """Verrou d'exécution non acquis (writer actif)."""


class FileLock:
    """Verrou d'exécution via fcntl.flock — atomicité noyau.

    Le fichier persiste comme trace (pid, 0600) mais la VÉRITÉ est le verrou
    flock : pas de logique stale/pid, pas de TOCTOU au takeover, et libération
    automatique par le noyau si le process meurt. Jamais d'unlink au release
    (évite la course fd-orphan où un waiter verrouille un inode retiré)."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
        self.path = Path(path)
        self.timeout = timeout
        self._fd: int | None = None

    def acquire(self) -> None:
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    os.truncate(fd, 0)
                    os.write(fd, f"{os.getpid()}\n".encode())
                except OSError:
                    pass
                self._fd = fd
                return
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise LockError(f"verrou actif: {self.path}")
                time.sleep(0.1)

    def release(self) -> None:
        if self._fd is None:
            return
        import fcntl
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def plan_sha256(plan_payload: dict) -> str:
    return hashlib.sha256(canonical_json(plan_payload)).hexdigest()


class State:
    """Accès SQLite transactionnel. Le fichier reste privé 0600."""

    def __init__(self, db_path: Path):
        self.path = db_path
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        os.chmod(self.path, 0o600)

    # --- processed ---------------------------------------------------------
    def mark_processed(self, mailbox: str, uidvalidity: int, uid: int, internaldate: str | None,
                       action: str | None, folder: str | None, ts: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT INTO processed (mailbox, uidvalidity, uid, first_seen, last_action, last_folder, last_ts) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(mailbox, uidvalidity, uid) DO UPDATE SET last_action=excluded.last_action, "
                "last_folder=excluded.last_folder, last_ts=excluded.last_ts",
                (mailbox, uidvalidity, uid, ts, action, folder, ts),
            )
            conn.commit()
        finally:
            conn.close()

    def seen_uids(self, mailbox: str, uidvalidity: int) -> set[int]:
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT uid FROM processed WHERE mailbox=? AND uidvalidity=?", (mailbox, uidvalidity)
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}

    def moved_counts_since(self, since_iso: str) -> dict[str, int]:
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT last_folder, COUNT(*) FROM processed "
                "WHERE last_action='move' AND last_ts>=? AND last_folder IS NOT NULL GROUP BY last_folder",
                (since_iso,),
            ).fetchall()
        finally:
            conn.close()
        return {r[0]: r[1] for r in rows}

    # --- plans --------------------------------------------------------------
    def create_plan(self, plan_id: str, created_at: str, expires_at: str, payload: dict) -> str:
        sha = plan_sha256(payload)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT INTO plans (id, created_at, expires_at, sha256, payload) VALUES (?,?,?,?,?)",
                (plan_id, created_at, expires_at, sha, canonical_json(payload).decode("utf-8")),
            )
            conn.commit()
        finally:
            conn.close()
        return sha

    def get_plan(self, plan_id: str) -> dict | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT id, created_at, expires_at, sha256, payload, status FROM plans WHERE id=?",
                (plan_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"id": row[0], "created_at": row[1], "expires_at": row[2], "sha256": row[3],
                "payload": json.loads(row[4]), "status": row[5]}

    def set_plan_status(self, plan_id: str, status: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("UPDATE plans SET status=? WHERE id=?", (status, plan_id))
            conn.commit()
        finally:
            conn.close()

    # --- autorisations (usage unique) ---------------------------------------
    def authorize_plan(self, plan_sha: str, kind: str, created_at: str) -> int:
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                "INSERT INTO authorizations (plan_sha, kind, created_at) VALUES (?,?,?)",
                (plan_sha, kind, created_at),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def consume_authorization(self, plan_sha: str, kind: str, consumed_at: str) -> int | None:
        """Consomme UNE autorisation non consommée (usage unique, atomique)."""
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                "UPDATE authorizations SET consumed_at=? "
                "WHERE id=(SELECT id FROM authorizations WHERE plan_sha=? AND kind=? AND consumed_at IS NULL "
                "ORDER BY created_at LIMIT 1) RETURNING id",
                (consumed_at, plan_sha, kind),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row[0]) if row else None
        finally:
            conn.close()

    # --- digests --------------------------------------------------------------
    def create_digest(self, digest_id: str, window_start: str, window_end: str, marker: str,
                      created_at: str, uidvalidity: int | None = None,
                      markdown: str | None = None, msg_uids: str | None = None) -> None:
        """Enregistre un digest pending. markdown + msg_uids servent à la
        réconciliation (repost APRÈS vérification du marqueur, jamais aveugle)."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT INTO digests (id, window_start, window_end, marker, state, created_at, "
                "uidvalidity, markdown, msg_uids) VALUES (?,?,?,?,?,?,?,?,?)",
                (digest_id, window_start, window_end, marker, "pending", created_at,
                 uidvalidity, markdown, msg_uids),
            )
            conn.commit()
        finally:
            conn.close()

    def get_digest(self, digest_id: str) -> dict | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT id, window_start, window_end, marker, state, post_id, uidvalidity, "
                "markdown, msg_uids, created_at, resolved_at FROM digests WHERE id=?",
                (digest_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"id": row[0], "window_start": row[1], "window_end": row[2], "marker": row[3],
                "state": row[4], "post_id": row[5], "uidvalidity": row[6], "markdown": row[7],
                "msg_uids": row[8], "created_at": row[9], "resolved_at": row[10]}

    def set_digest_state(self, digest_id: str, state: str, post_id: str | None = None,
                         resolved_at: str | None = None) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "UPDATE digests SET state=?, post_id=COALESCE(?, post_id), resolved_at=COALESCE(?, resolved_at) "
                "WHERE id=?",
                (state, post_id, resolved_at, digest_id),
            )
            conn.commit()
        finally:
            conn.close()

    def last_confirmed_digest(self) -> dict | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT id, window_start, window_end, resolved_at FROM digests "
                "WHERE state='sent' ORDER BY resolved_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"id": row[0], "window_start": row[1], "window_end": row[2], "resolved_at": row[3]}

    def uncertain_digests(self) -> list[dict]:
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT id, window_start, window_end, marker, post_id FROM digests WHERE state='uncertain'"
            ).fetchall()
        finally:
            conn.close()
        return [{"id": r[0], "window_start": r[1], "window_end": r[2], "marker": r[3], "post_id": r[4]}
                for r in rows]

    def mark_digest_msg(self, mailbox: str, uidvalidity: int, uid: int, internaldate: str | None,
                        digest_id: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO digested_msgs (mailbox, uidvalidity, uid, internaldate, digest_id) "
                "VALUES (?,?,?,?,?)",
                (mailbox, uidvalidity, uid, internaldate, digest_id),
            )
            conn.commit()
        finally:
            conn.close()

    def digested_msg_keys(self, mailbox: str, uidvalidity: int) -> set[int]:
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT uid FROM digested_msgs WHERE mailbox=? AND uidvalidity=?",
                (mailbox, uidvalidity),
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}

    # --- résultats de déplacements par plan ---------------------------------
    def set_move_result(self, plan_id: str, uid: int, status: str, detail: str | None = None) -> None:
        """status : done | failed | uncertain (réconcilié ensuite)."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT INTO plan_results (plan_id, uid, status, detail) VALUES (?,?,?,?) "
                "ON CONFLICT(plan_id, uid) DO UPDATE SET status=excluded.status, detail=excluded.detail",
                (plan_id, uid, status, detail),
            )
            conn.commit()
        finally:
            conn.close()

    def get_move_results(self, plan_id: str) -> list[dict]:
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT uid, status, detail FROM plan_results WHERE plan_id=? ORDER BY uid",
                (plan_id,),
            ).fetchall()
        finally:
            conn.close()
        return [{"uid": r[0], "status": r[1], "detail": r[2]} for r in rows]
