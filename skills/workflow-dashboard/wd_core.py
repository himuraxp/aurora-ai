"""Workflow Dashboard — Universal Core (contrat ProgressTopic v1).

Contrat de progression universel publié par les sources autorisées (CLI de
publication, relais todowrite, adaptateurs natifs). Le dashboard est un
lecteur strict : il n'écrit JAMAIS et ne décide jamais qu'une tâche est
terminée — il interprète les transitions publiées.

Layout disque (canonical, hors dépôts) :

    <root>/<scope-key>/<topicId>.json

- root          : ~/.config/opencode/progress (override : WD_PROGRESS_DIR, tests/pilotes)
- scope-key     : "global" | "worktree-<sha1_12(realpath)>" | "session-<sanitized>"
- topicId       : UUID v4 canonique généré au create (identité d'exécution)

Garanties d'écriture : verrou par fichier (O_CREAT|O_EXCL + retry ; stale =
âge dépassé ET pid mort — jamais un verrou de writer actif), revision++ par
écriture, tmp+os.replace atomique, lecture tolérante (fichier corrompu =>
signalement, jamais un crash).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

SCHEMA_VERSION = 1

PROGRESS_STATUSES = ("PENDING", "RUNNING", "DONE", "FAILED", "BLOCKED", "SKIPPED")
TERMINAL_STATUSES = ("DONE", "FAILED", "SKIPPED")  # BLOCKED n'est PAS terminal
KINDS = ("skill", "plan", "custom")
SCOPES = ("global", "worktree", "session")
SOURCES = ("task-workflow", "todowrite-relay", "orchestrator-cli")

DEFAULT_PROGRESS_DIR = os.path.expanduser("~/.config/opencode/progress")
ENV_PROGRESS_DIR = "WD_PROGRESS_DIR"

_LOCK_POLL_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_STALE_AGE_SECONDS = 30.0


class ContractError(ValueError):
    """Violation du contrat ProgressTopic (validation refusée)."""


class LockError(RuntimeError):
    """Verrou non acquis dans le délai imparti (writer concurrent actif)."""


# ---------------------------------------------------------------------------
# Helpers temps / identité
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Timestamp ISO-8601 timezone-aware (format canonique du contrat)."""
    return datetime.now(timezone.utc).isoformat()


def is_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))  # tw_state._is_iso compatible
    except ValueError:
        return False
    return True


def new_topic_id() -> str:
    """Identité d'exécution : UUID v4 canonique (improvement t4 #1)."""
    return str(uuid.uuid4())


def canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Validation du contrat
# ---------------------------------------------------------------------------


def validate_step(step: Any) -> None:
    if not isinstance(step, dict):
        raise ContractError("step must be an object")
    step_id = step.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        raise ContractError("step.id must be a non-empty string")
    label = step.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ContractError(f"step {step_id!r}: label must be a non-empty string")
    status = step.get("status")
    if status not in PROGRESS_STATUSES:
        raise ContractError(
            f"step {step_id!r}: status {status!r} not in {list(PROGRESS_STATUSES)}"
        )
    detail = step.get("detail")
    if detail is not None and not isinstance(detail, str):
        raise ContractError(f"step {step_id!r}: detail must be a string or null")
    updated = step.get("updatedAt")
    if updated is not None and not is_iso_datetime(updated):
        raise ContractError(f"step {step_id!r}: updatedAt must be ISO-8601")
    parent = step.get("parentId")
    if parent is not None:
        if not isinstance(parent, str) or not parent.strip():
            raise ContractError(f"step {step_id!r}: parentId must be a non-empty string")
        if parent == step_id:
            raise ContractError(f"step {step_id!r}: parentId must not self-reference")


def validate_topic(topic: Any) -> None:
    """Validation complète du contrat — lève ContractError (messages lisibles)."""
    if not isinstance(topic, dict):
        raise ContractError("topic must be an object")
    if topic.get("schemaVersion") != SCHEMA_VERSION:
        raise ContractError(f"schemaVersion must be {SCHEMA_VERSION}")
    if not canonical_uuid(topic.get("topicId")):
        raise ContractError("topicId must be a canonical UUID string")
    title = topic.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ContractError("title must be a non-empty string")
    if topic.get("kind") not in KINDS:
        raise ContractError(f"kind {topic.get('kind')!r} not in {list(KINDS)}")
    if topic.get("source") not in SOURCES:
        raise ContractError(f"source {topic.get('source')!r} not in {list(SOURCES)}")
    scope = topic.get("scope")
    if scope not in SCOPES:
        raise ContractError(f"scope {scope!r} not in {list(SCOPES)}")
    session_id = topic.get("sessionId")
    worktree_path = topic.get("worktreePath")
    if scope == "worktree" and (not isinstance(worktree_path, str) or not worktree_path.strip()):
        raise ContractError("scope=worktree requires a non-empty worktreePath")
    if scope == "session" and (not isinstance(session_id, str) or not session_id.strip()):
        raise ContractError("scope=session requires a non-empty sessionId")
    if session_id is not None and not isinstance(session_id, str):
        raise ContractError("sessionId must be a string or null")
    if worktree_path is not None and not isinstance(worktree_path, str):
        raise ContractError("worktreePath must be a string or null")
    parent = topic.get("parentTopicId")
    if parent is not None and not canonical_uuid(parent):
        raise ContractError("parentTopicId must be a canonical UUID or null")
    steps = topic.get("steps")
    if not isinstance(steps, list):
        raise ContractError("steps must be a list")
    seen: set = set()
    for step in steps:
        validate_step(step)
        if step["id"] in seen:
            raise ContractError(f"duplicate step id: {step['id']!r}")
        seen.add(step["id"])
    for step in steps:
        parent = step.get("parentId")
        if parent is not None and parent not in seen:
            raise ContractError(f"step {step['id']!r}: parentId {parent!r} unknown")
    if not is_iso_datetime(topic.get("createdAt")):
        raise ContractError("createdAt must be ISO-8601")
    if not is_iso_datetime(topic.get("updatedAt")):
        raise ContractError("updatedAt must be ISO-8601")
    revision = topic.get("revision")
    if type(revision) is not int or revision < 1:
        raise ContractError("revision must be an integer >= 1")


# ---------------------------------------------------------------------------
# Stockage : chemins, scoping, écriture atomique
# ---------------------------------------------------------------------------


def progress_dir() -> str:
    return os.environ.get(ENV_PROGRESS_DIR) or DEFAULT_PROGRESS_DIR


def _sanitize_session_id(session_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", session_id):
        return session_id
    return hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:12]


def scope_key(scope: str, worktree_path: Optional[str] = None,
              session_id: Optional[str] = None) -> str:
    """Dossier dérivé du scope : identité ≠ scope ≠ stockage (séparation t3)."""
    if scope == "global":
        return "global"
    if scope == "worktree":
        if not worktree_path:
            raise ContractError("scope=worktree requires worktreePath")
        real = os.path.realpath(os.path.expanduser(worktree_path))
        digest = hashlib.sha1(real.encode("utf-8")).hexdigest()[:12]
        return f"worktree-{digest}"
    if scope == "session":
        if not session_id:
            raise ContractError("scope=session requires sessionId")
        return f"session-{_sanitize_session_id(session_id)}"
    raise ContractError(f"unknown scope: {scope!r}")


def topic_relpath(topic: Dict[str, Any]) -> str:
    return os.path.join(scope_key(topic["scope"], topic.get("worktreePath"),
                                   topic.get("sessionId")),
                        f"{topic['topicId']}.json")


def topic_abspath(topic: Dict[str, Any], root: Optional[str] = None) -> str:
    return os.path.join(root or progress_dir(), topic_relpath(topic))


def _write_atomic(path: str, data: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = None, None
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=".wd-", suffix=".tmp",
                                   dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    """Lecture tolérante : None si illisible/corrompu (dernier snapshot invalide)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def read_topic(path: str) -> Optional[Dict[str, Any]]:
    data = _read_json(path)
    if data is None:
        return None
    try:
        validate_topic(data)
    except ContractError:
        return None
    return data


def find_topic_path(topic_id: str, root: Optional[str] = None) -> Optional[str]:
    """Un topicId est unique globalement : scan des dossiers de scope."""
    root = root or progress_dir()
    if not os.path.isdir(root):
        return None
    for entry in sorted(os.listdir(root)):
        candidate = os.path.join(root, entry, f"{topic_id}.json")
        if os.path.isfile(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Verrou par fichier (improvement t4 #2 : stale = âge ET pid mort)
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # le process existe, il appartient à un autre utilisateur
    except OSError:
        return False
    return True


class FileLock:
    """Verrou exclusif par fichier, takeover stale seulement si le pid est mort."""

    def __init__(self, path: str, timeout: float = _LOCK_TIMEOUT_SECONDS,
                 poll: float = _LOCK_POLL_SECONDS,
                 stale_age: float = _LOCK_STALE_AGE_SECONDS) -> None:
        self.path = path
        self.timeout = timeout
        self.poll = poll
        self.stale_age = stale_age
        self._held = False

    def acquire(self) -> None:
        parent = os.path.dirname(self.path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"{os.getpid()} {now_iso()}\n")
                self._held = True
                return
            except FileExistsError:
                self._takeover_if_stale()
                if time.monotonic() >= deadline:
                    raise LockError(f"lock busy: {self.path}")
                time.sleep(self.poll)

    def _takeover_if_stale(self) -> None:
        try:
            stat = os.stat(self.path)
        except OSError:
            return  # le lock a disparu : prochain tour le crée
        age = time.time() - stat.st_mtime
        if age < self.stale_age:
            return
        pid = None
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                first = (handle.read(64) or "").split()
            if first:
                pid = int(first[0])
        except (OSError, ValueError):
            pid = None
        if pid is not None and _pid_alive(pid):
            return  # writer actif : jamais de takeover, même intra-process (t4 #2)
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def release(self) -> None:
        if not self._held:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                first = (handle.read(64) or "").split()
            if first and first[0] == str(os.getpid()):
                os.unlink(self.path)
        except OSError:
            pass
        self._held = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Mutations (toutes sous verrou, révision++ à chaque écriture)
# ---------------------------------------------------------------------------


def _mutate(path: str, mutator: Callable[[Optional[Dict[str, Any]]], Dict[str, Any]]) -> Dict[str, Any]:
    lock = FileLock(path + ".lock")
    lock.acquire()
    try:
        existing = read_topic(path)
        topic = mutator(existing)
        topic["revision"] = (existing["revision"] if existing else 0) + 1
        topic["updatedAt"] = now_iso()
        validate_topic(topic)
        _write_atomic(path, json.dumps(topic, indent=2, ensure_ascii=False) + "\n")
        return topic
    finally:
        lock.release()


def create_topic(title: str, kind: str, source: str, scope: str,
                 steps: Optional[List[Dict[str, Any]]] = None,
                 session_id: Optional[str] = None,
                 worktree_path: Optional[str] = None,
                 parent_topic_id: Optional[str] = None,
                 root: Optional[str] = None) -> Dict[str, Any]:
    now = now_iso()
    topic: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "topicId": new_topic_id(),
        "title": title,
        "kind": kind,
        "source": source,
        "scope": scope,
        "steps": [],
        "createdAt": now,
        "updatedAt": now,
        "revision": 1,
    }
    if session_id is not None:
        topic["sessionId"] = session_id
    if worktree_path is not None:
        topic["worktreePath"] = worktree_path
    if parent_topic_id is not None:
        topic["parentTopicId"] = parent_topic_id
    for spec in steps or []:
        step = {"id": spec["id"], "label": spec["label"],
                "status": "PENDING"}
        if spec.get("parentId"):
            step["parentId"] = spec["parentId"]
        if spec.get("detail"):
            step["detail"] = spec["detail"]
        topic["steps"].append(step)
    validate_topic(topic)
    path = topic_abspath(topic, root=root)
    lock = FileLock(path + ".lock")
    lock.acquire()
    try:
        if os.path.exists(path):
            raise ContractError(f"topic already exists: {topic['topicId']}")
        _write_atomic(path, json.dumps(topic, indent=2, ensure_ascii=False) + "\n")
    finally:
        lock.release()
    return topic


def update_step(topic_id: str, step_id: str, status: str,
                detail: Optional[str] = None, label: Optional[str] = None,
                root: Optional[str] = None) -> Dict[str, Any]:
    path = find_topic_path(topic_id, root=root)
    if path is None:
        raise ContractError(f"topic not found: {topic_id}")
    if status not in PROGRESS_STATUSES:
        raise ContractError(f"status {status!r} not in {list(PROGRESS_STATUSES)}")

    def mutator(existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if existing is None:
            raise ContractError(f"topic unreadable: {topic_id}")
        for step in existing["steps"]:
            if step["id"] == step_id:
                step["status"] = status
                step["updatedAt"] = now_iso()
                if detail is not None:
                    step["detail"] = detail
                if label is not None:
                    step["label"] = label
                return existing
        raise ContractError(f"step not found: {step_id}")

    return _mutate(path, mutator)


def append_step(topic_id: str, spec: Dict[str, Any],
                root: Optional[str] = None) -> Dict[str, Any]:
    """Ajoute une étape SOUS VERROU (lecture+écriture dans _mutate).

    Review J1 #2 : un read-modify-write hors verro perdait les ajouts
    concurrents — l'ajout est désormais atomique par rapport aux autres
    mutations (step, set-steps, close)."""
    path = find_topic_path(topic_id, root=root)
    if path is None:
        raise ContractError(f"topic not found: {topic_id}")

    def mutator(existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if existing is None:
            raise ContractError(f"topic unreadable: {topic_id}")
        if any(step["id"] == spec["id"] for step in existing["steps"]):
            raise ContractError(f"duplicate step id: {spec['id']!r}")
        step: Dict[str, Any] = {"id": spec["id"], "label": spec["label"],
                                "status": "PENDING"}
        if spec.get("parentId"):
            step["parentId"] = spec["parentId"]
        if spec.get("detail"):
            step["detail"] = spec["detail"]
        existing["steps"].append(step)
        return existing

    return _mutate(path, mutator)


def set_steps(topic_id: str, step_specs: List[Dict[str, Any]],
              root: Optional[str] = None) -> Dict[str, Any]:
    """Change-plan : les steps réécrits, états conservés pour les ids stables
    (règle validée t4) ; les ids absents du nouveau plan disparaissent."""
    path = find_topic_path(topic_id, root=root)
    if path is None:
        raise ContractError(f"topic not found: {topic_id}")

    def mutator(existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if existing is None:
            raise ContractError(f"topic unreadable: {topic_id}")
        previous = {step["id"]: step for step in existing["steps"]}
        steps: List[Dict[str, Any]] = []
        for spec in step_specs:
            old = previous.get(spec["id"])
            step: Dict[str, Any] = {"id": spec["id"], "label": spec["label"],
                                    "status": old["status"] if old else "PENDING"}
            if spec.get("parentId"):
                step["parentId"] = spec["parentId"]
            detail = old.get("detail") if old else spec.get("detail")
            if detail:
                step["detail"] = detail
            if old and old.get("updatedAt"):
                step["updatedAt"] = old["updatedAt"]
            steps.append(step)
        existing["steps"] = steps
        return existing

    return _mutate(path, mutator)


def close_topic(topic_id: str, terminal_status: str,
                detail: Optional[str] = None,
                root: Optional[str] = None) -> Dict[str, Any]:
    """Clôture éditeur : les steps non terminaux passent au statut terminal
    (décision de publication de l'orchestrateur, tracée par detail)."""
    if terminal_status not in TERMINAL_STATUSES:
        raise ContractError(
            f"terminal_status {terminal_status!r} not in {list(TERMINAL_STATUSES)}")
    path = find_topic_path(topic_id, root=root)
    if path is None:
        raise ContractError(f"topic not found: {topic_id}")

    def mutator(existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if existing is None:
            raise ContractError(f"topic unreadable: {topic_id}")
        now = now_iso()
        for step in existing["steps"]:
            previous_status = step["status"]
            if previous_status not in TERMINAL_STATUSES:
                step["status"] = terminal_status
                step["updatedAt"] = now
                note = detail or "closed by publisher"
                previous_detail = step.get("detail")
                step["detail"] = f"{note} (was {previous_status})" if not previous_detail \
                    else f"{note} (was {previous_status}: {previous_detail})"
        return existing

    return _mutate(path, mutator)


# ---------------------------------------------------------------------------
# Lectures / dérivation (affichage — jamais stocké)
# ---------------------------------------------------------------------------


def list_topics(root: Optional[str] = None,
                scope: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tous les topics, tolérant : fichier corrompu => entrée error, pas de crash."""
    root = root or progress_dir()
    entries: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return entries
    for scope_dir in sorted(os.listdir(root)):
        scope_path = os.path.join(root, scope_dir)
        if scope:
            if scope == "global":
                if scope_dir != "global":
                    continue
            elif not scope_dir.startswith(f"{scope}-"):
                continue  # worktree-<hash> / session-<id> : match par préfixe
        if not os.path.isdir(scope_path):
            continue
        for name in sorted(os.listdir(scope_path)):
            if not name.endswith(".json") or name.startswith("."):
                continue
            path = os.path.join(scope_path, name)
            topic = read_topic(path)
            entry: Dict[str, Any] = {"path": path, "scopeDir": scope_dir}
            if topic is None:
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        json.load(handle)
                    error = "topic invalid (contract)"
                except (OSError, ValueError) as exc:
                    error = f"unreadable: {exc}"
                entry.update({"topic": None, "error": error})
            else:
                entry.update({"topic": topic, "error": None})
            entries.append(entry)
    return entries


def _top_level_steps(topic: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Steps de haut niveau uniquement — jamais de double comptage (t3 #5)."""
    return [s for s in topic["steps"] if not s.get("parentId")]


def compute_progress(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Progression dérivée à l'affichage : avancement ≠ réussite (t2)."""
    top = _top_level_steps(topic)
    counts = {status: 0 for status in PROGRESS_STATUSES}
    for step in top:
        counts[step["status"]] = counts.get(step["status"], 0) + 1
    total = len(top)
    terminal = sum(counts[s] for s in TERMINAL_STATUSES)
    return {
        "total": total,
        "counts": counts,
        "terminalCount": terminal,
        "terminalRatio": round(terminal / total, 4) if total else 0.0,
        "derivedStatus": derive_status(topic),
    }


def derive_status(topic: Dict[str, Any]) -> str:
    """Statut global DÉRIVÉ (jamais éditable, jamais stocké — position t3/t4).
    Running > Blocked > (tous terminaux : Failed > Done > Skipped) > Pending."""
    top = _top_level_steps(topic)
    if not top:
        return "PENDING"
    statuses = [s["status"] for s in top]
    if "RUNNING" in statuses:
        return "RUNNING"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if all(s in TERMINAL_STATUSES for s in statuses):
        if "FAILED" in statuses:
            return "FAILED"
        if "DONE" in statuses:
            return "DONE"
        return "SKIPPED"
    if any(s in TERMINAL_STATUSES for s in statuses):
        return "RUNNING"  # mélange terminaux + PENDING : exécution en cours
    return "PENDING"
