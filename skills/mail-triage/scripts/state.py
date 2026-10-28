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
from datetime import datetime, timezone
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
CREATE TABLE IF NOT EXISTS digest_refs (
  digest_id TEXT NOT NULL,
  ref TEXT NOT NULL,
  mailbox TEXT NOT NULL,
  uidvalidity INTEGER NOT NULL,
  uid INTEGER NOT NULL,
  from_addr TEXT NOT NULL,
  subject TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (digest_id, ref)
);
CREATE TABLE IF NOT EXISTS interactive_commands (
  post_id TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  sender TEXT NOT NULL,
  verb TEXT NOT NULL,
  status TEXT NOT NULL,
  reply_post_id TEXT,
  processed_at TEXT
);
CREATE TABLE IF NOT EXISTS interactive_checkpoint (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_created_at INTEGER NOT NULL,
  last_post_id TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_seq (
  kind TEXT PRIMARY KEY,
  next_value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  source_post_id TEXT,
  confirmation_post_id TEXT
);
CREATE TABLE IF NOT EXISTS rule_operations (
  operation_id TEXT PRIMARY KEY,
  rule_id TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_items (
  mailbox TEXT NOT NULL,
  uidvalidity INTEGER NOT NULL,
  uid INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'new',
  from_addr TEXT,
  subject TEXT,
  first_seen TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (mailbox, uidvalidity, uid)
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

    # --- canal interactif (ARCHITECTURE §11) ----------------------------------

    def store_digest_refs(self, rows: list[dict]) -> None:
        """Références courtes du digest publié (immuables, expirent en 48 h)."""
        conn = sqlite3.connect(self.path)
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO digest_refs "
                "(digest_id, ref, mailbox, uidvalidity, uid, from_addr, subject, kind, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(r["digest_id"], r["ref"], r["mailbox"], r["uidvalidity"], r["uid"],
                  r["from_addr"], r["subject"], r["kind"], r["created_at"], r["expires_at"])
                 for r in rows],
            )
            conn.commit()
        finally:
            conn.close()

    def resolve_digest_ref(self, ref: str, now_iso: str) -> dict | None:
        """Compat J2 : résolution simple (None si inconnue/expirée/ambiguïté)."""
        got = self.resolve_ref(ref, now_iso)
        return got["ref"] if got["status"] == "ok" else None

    def resolve_ref(self, ref: str, now_iso: str) -> dict:
        """Résolution non ambiguë (contrat §11.5 corrigé t10) : 0 ligne =
        unknown/expired ; > 1 ligne active = ambiguous (REFUS, jamais de
        résolution arbitraire vers « le dernier digest »)."""
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT digest_id, ref, mailbox, uidvalidity, uid, from_addr, subject, kind, "
                "expires_at FROM digest_refs WHERE ref=?", (ref,),
            ).fetchall()
        finally:
            conn.close()
        active = [r for r in rows if r[8] > now_iso]
        if len(active) > 1:
            return {"status": "ambiguous", "ref": None}
        if not active:
            return {"status": "expired" if rows else "unknown", "ref": None}
        r = active[0]
        return {"status": "ok", "ref": {"digest_id": r[0], "ref": r[1], "mailbox": r[2],
                                        "uidvalidity": r[3], "uid": r[4], "from_addr": r[5],
                                        "subject": r[6], "kind": r[7]}}

    def next_ref_number(self, kind: str) -> int:
        """Compteur monotone par type (a/n/l/p) — références GLOBALEMENT
        non ambiguës (t10) : jamais réutilisées, même après expiration.
        Atomicité (F-02 review J3) : BEGIN IMMEDIATE sérialise SELECT+UPDATE
        (SQLite writer unique) — deux appelants concurrents ne peuvent pas
        allouer le même numéro. Initialisation : max(numéro existant pour ce
        type) + 1 (les refs pré-compteur #n1 des premiers digests V4 restent
        uniques). Invariant ISO : tous les horodatages sont aware-UTC "+00:00"
        (comparaisons lexicographiques, F-05)."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")  # verrou d'écriture immédiat (TOCTOU)
            row = conn.execute("SELECT next_value FROM ref_seq WHERE kind=?", (kind,)).fetchone()
            if row is None:
                existing = conn.execute("SELECT ref FROM digest_refs WHERE ref LIKE ?",
                                        (kind + r"%",)).fetchall()
                max_n = 0
                for (r,) in existing:
                    digits = r[len(kind):]
                    if digits.isdigit():
                        max_n = max(max_n, int(digits))
                # toutes propositions confondues : les p-ref vivent dans proposals
                if kind == "p":
                    prow = conn.execute(
                        "SELECT proposal_id FROM proposals WHERE proposal_id LIKE ?",
                        ("p%",)).fetchall()
                    for (pid,) in prow:
                        digits = pid[1:]
                        if digits.isdigit():
                            max_n = max(max_n, int(digits))
                nxt = max_n + 1
            else:
                nxt = int(row[0])
            conn.execute(
                "INSERT INTO ref_seq (kind, next_value) VALUES (?,?) "
                "ON CONFLICT(kind) DO UPDATE SET next_value=excluded.next_value",
                (kind, nxt + 1))
            conn.commit()
        finally:
            conn.close()
        return nxt

    def record_command(self, post_id: str, channel_id: str, created_at: int,
                       sender: str, verb: str) -> bool:
        """Registre post_id PRIMARY KEY : idempotence (rejeu impossible).
        Retourne True si le post est NOUVEAU (à traiter), False si déjà connu."""
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO interactive_commands "
                "(post_id, channel_id, created_at, sender, verb, status) "
                "VALUES (?,?,?,?,?, 'received')",
                (post_id, channel_id, created_at, sender, verb),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_command_result(self, post_id: str, status: str, reply_post_id: str | None,
                           processed_at: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "UPDATE interactive_commands SET status=?, reply_post_id=?, processed_at=? "
                "WHERE post_id=?",
                (status, reply_post_id, processed_at, post_id),
            )
            conn.commit()
        finally:
            conn.close()

    def interactive_checkpoint(self) -> dict | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT last_created_at, last_post_id FROM interactive_checkpoint WHERE id=1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"last_created_at": row[0], "last_post_id": row[1]}

    def set_interactive_checkpoint(self, last_created_at: int, last_post_id: str,
                                   updated_at: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT INTO interactive_checkpoint (id, last_created_at, last_post_id, updated_at) "
                "VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "last_created_at=excluded.last_created_at, last_post_id=excluded.last_post_id, "
                "updated_at=excluded.updated_at",
                (last_created_at, last_post_id, updated_at),
            )
            conn.commit()
        finally:
            conn.close()

    def create_proposal(self, proposal: dict) -> None:
        """Autorisation distante à usage unique (§11.4) — schema posé en J1,
        rempli par J3/J4."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO proposals "
                "(proposal_id, kind, owner_user_id, channel_id, action, target_version, "
                " created_at, expires_at, status, source_post_id, confirmation_post_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (proposal["proposal_id"], proposal["kind"], proposal["owner_user_id"],
                 proposal["channel_id"], proposal["action"], proposal["target_version"],
                 proposal["created_at"], proposal["expires_at"],
                 proposal.get("status", "pending"), proposal.get("source_post_id"),
                 proposal.get("confirmation_post_id")),
            )
            conn.commit()
        finally:
            conn.close()

    # --- limites interactives (§11.6) + lecture/annulation propositions -------

    def pending_proposals_count(self, now_iso: str | None = None) -> int:
        """Propositions ACTIVES uniquement (F-01 review J3) : une proposition
        expirée n'est plus « simultanée » (§11.6) et doit libérer le budget.
        Le quota quotidien de règles (rule_proposals_since) ne filtre PAS :
        les annulées continuent de compter (anti-boucle annule/recrée)."""
        if now_iso is None:
            now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.path)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM proposals WHERE status='pending' AND expires_at > ?",
                (now_iso,)).fetchone()
        finally:
            conn.close()
        return int(n)

    def expire_stale_proposals(self, now_iso: str) -> int:
        """Balayage d'expiration : pending + périmées → status 'expired'
        (réconciliable, jamais re-consommables). Retourne le nombre expirées."""
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                "UPDATE proposals SET status='expired' "
                "WHERE status='pending' AND expires_at <= ?", (now_iso,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def rule_proposals_since(self, since_iso: str) -> int:
        conn = sqlite3.connect(self.path)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM proposals WHERE kind='rule' AND created_at >= ?",
                (since_iso,)).fetchone()
        finally:
            conn.close()
        return int(n)

    def commands_in_window(self, since_ms: int) -> int:
        conn = sqlite3.connect(self.path)
        try:
            (n,) = conn.execute(
                "SELECT COUNT(*) FROM interactive_commands WHERE created_at >= ?",
                (since_ms,)).fetchone()
        finally:
            conn.close()
        return int(n)

    def get_proposal(self, proposal_id: str) -> dict | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT proposal_id, kind, owner_user_id, channel_id, action, target_version, "
                "created_at, expires_at, status, source_post_id, confirmation_post_id "
                "FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"proposal_id": row[0], "kind": row[1], "owner_user_id": row[2],
                "channel_id": row[3], "action": row[4], "target_version": row[5],
                "created_at": row[6], "expires_at": row[7], "status": row[8],
                "source_post_id": row[9], "confirmation_post_id": row[10]}

    def set_proposal_status(self, proposal_id: str, status: str,
                            confirmation_post_id: str | None = None) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "UPDATE proposals SET status=?, confirmation_post_id=COALESCE(?, confirmation_post_id) "
                "WHERE proposal_id=?",
                (status, confirmation_post_id, proposal_id))
            conn.commit()
        finally:
            conn.close()

    def reserve_proposal(self, proposal_id: str, now_iso: str,
                         confirmation_post_id: str) -> bool:
        """Réservation ATOMIQUE pending→executing (§11.4, J4) : usage unique
        garanti — UPDATE conditionnel sur (pending + non expirée) ; deux
        confirmations concurrentes ne peuvent pas passer toutes les deux
        (un seul writer SQLite, la seconde obtient rowcount=0)."""
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                "UPDATE proposals SET status='executing', "
                "confirmation_post_id=COALESCE(?, confirmation_post_id) "
                "WHERE proposal_id=? AND status='pending' AND expires_at > ?",
                (confirmation_post_id, proposal_id, now_iso))
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()

    def timeout_stale_executing(self, older_than_iso: str) -> int:
        """Sweep des 'executing' orphelins (crash entre réservation et fin
        d'exécution) : status → 'uncertain' (réconciliable, jamais
        re-consommable — usage unique préservé)."""
        conn = sqlite3.connect(self.path)
        try:
            cur = conn.execute(
                "UPDATE proposals SET status='uncertain' "
                "WHERE status='executing' AND created_at < ?", (older_than_iso,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def rule_operation_applied(self, operation_id: str) -> dict | None:
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT operation_id, rule_id, applied_at FROM rule_operations "
                "WHERE operation_id=?", (operation_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"operation_id": row[0], "rule_id": row[1], "applied_at": row[2]}

    def record_rule_operation(self, operation_id: str, rule_id: str, applied_at: str) -> None:
        """Traçabilité operation_id (§11.7) : réconciliation sans ambiguïté
        après une coupure suivant os.replace."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO rule_operations (operation_id, rule_id, applied_at) "
                "VALUES (?,?,?)", (operation_id, rule_id, applied_at))
            conn.commit()
        finally:
            conn.close()

    # --- J4bis (§12.4, D6) : état workflow persistant --------------------------------

    def upsert_workflow_items(self, rows: list[dict], now_iso: str) -> None:
        """Nouveaux items = 'new' ; un item CONNU garde son état (jamais de
        réinitialisation — l'historique anti re-proposition est préservé)."""
        conn = sqlite3.connect(self.path)
        try:
            for r in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO workflow_items "
                    "(mailbox, uidvalidity, uid, state, from_addr, subject, first_seen, updated_at) "
                    "VALUES (?,?,?,'new',?,?,?,?)",
                    (r["mailbox"], r["uidvalidity"], r["uid"],
                     r.get("from_addr"), r.get("subject"), now_iso, now_iso))
            conn.commit()
        finally:
            conn.close()

    def resolve_workflow_items(self, present_keys: set, frozen_mailboxes: set,
                               now_iso: str) -> int:
        """new/pending ABSENTS du scan → resolved (déplacés ou clôturés) — jamais
        re-proposés. 'uncertain' reste uncertain (réconciliation opérateur).
        Review F-04 : les dossiers 'frozen' (scan partiel, cap dépassé) ne sont
        JAMAIS résolus — fail-closed. Retourne le nombre d'items résolus."""
        conn = sqlite3.connect(self.path)
        resolved = 0
        try:
            rows = conn.execute(
                "SELECT mailbox, uidvalidity, uid FROM workflow_items "
                "WHERE state IN ('new','pending')").fetchall()
            for mailbox, uv, uid in rows:
                if mailbox in frozen_mailboxes:
                    continue
                if (mailbox, uv, uid) not in present_keys:
                    conn.execute(
                        "UPDATE workflow_items SET state='resolved', updated_at=? "
                        "WHERE mailbox=? AND uidvalidity=? AND uid=?",
                        (now_iso, mailbox, uv, uid))
                    resolved += 1
            conn.commit()
        finally:
            conn.close()
        return resolved

    def workflow_items_by_state(self, states: list[str]) -> list[dict]:
        conn = sqlite3.connect(self.path)
        placeholders = ",".join("?" for _ in states)
        try:
            rows = conn.execute(
                f"SELECT mailbox, uidvalidity, uid, state, from_addr, subject, first_seen "
                f"FROM workflow_items WHERE state IN ({placeholders}) "
                f"ORDER BY first_seen ASC", states).fetchall()
        finally:
            conn.close()
        return [{"mailbox": r[0], "uidvalidity": r[1], "uid": r[2], "state": r[3],
                 "from_addr": r[4], "subject": r[5], "first_seen": r[6]} for r in rows]

    def set_workflow_item_state(self, mailbox: str, uidvalidity: int, uid: int,
                                state: str, now_iso: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "UPDATE workflow_items SET state=?, updated_at=? "
                "WHERE mailbox=? AND uidvalidity=? AND uid=?",
                (state, now_iso, mailbox, uidvalidity, uid))
            conn.commit()
        finally:
            conn.close()

    def active_ref_for_key(self, mailbox: str, uidvalidity: int, uid: int,
                           now_iso: str) -> str | None:
        """Ref ACTIVE (non expirée) pointant vers ce message — évite d'allouer
        une ref fraîche à un item dont la ref courante est toujours valide."""
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT ref FROM digest_refs WHERE mailbox=? AND uidvalidity=? AND uid=? "
                "AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                (mailbox, uidvalidity, uid, now_iso)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
