"""Chargement et validation du config.json privé — fail-closed (aucun défaut implicite)."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "opencode" / "mail-triage"
DEFAULT_ENV_FILE = Path.home() / ".config" / "opencode" / ".env"

# Dossiers destinations interdits quel que soit le nom (invariant 2).
FORBIDDEN_DESTINATION_PATTERNS = (
    "trash", "corbeille", "poubelle", "junk", "spam", "indesirable", "indésirable",
    "deleted", "supprime", "supprimé", "drafts", "brouillons", "sent", "envoyé",
)

# Frontière de mot + pluriel optionnel : "sent" interdit mais "Sentry" autorisé.
# Les chiffres AVANT le mot neutralisent le match, PAS après (Spam2 reste interdit).
_FORBIDDEN_RES = tuple(
    re.compile(rf"(?i)(?<![a-z0-9]){re.escape(p)}s?(?![a-z])")
    for p in FORBIDDEN_DESTINATION_PATTERNS
)


def destination_is_forbidden(folder: str) -> bool:
    """True si un segment du chemin correspond à un dossier interdit (invariant 2)."""
    lowered = (folder or "").lower()
    for seg in lowered.split("/"):
        seg = seg.strip()
        if not seg:
            continue
        if any(rx.search(seg) for rx in _FORBIDDEN_RES):
            return True
    return False


class ConfigError(Exception):
    """Configuration absente, illisible ou invalide."""


class SecretError(Exception):
    """Secret requis absent."""


def config_dir(override: str | None = None) -> Path:
    """Répertoire de config privé : --config-dir > env MAIL_TRIAGE_CONFIG_DIR > défaut."""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("MAIL_TRIAGE_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_CONFIG_DIR


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse minimal KEY=VALUE (jamais de valeur retournée en log)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


_ENV_FILE_CACHE: dict[Path, dict[str, str]] = {}


def get_secret(name: str, env_file: Path | None = None) -> str:
    """Secret : process env d'abord, puis ~/.config/opencode/.env (fallback launchd)."""
    value = os.environ.get(name)
    if value:
        return value
    path = env_file or DEFAULT_ENV_FILE
    if path not in _ENV_FILE_CACHE:
        _ENV_FILE_CACHE[path] = _read_env_file(path)
    value = _ENV_FILE_CACHE[path].get(name)
    if value:
        return value
    raise SecretError(f"Secret manquant: {name}")


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ConfigError(message)


def _validate_destination(folder: str) -> None:
    _require(isinstance(folder, str) and folder.strip(), "destination vide dans l'allowlist")
    # V1 : allowlist ASCII imprimable, espaces internes incluses (l'espace 0x20
    # n'est pas affecté par mUTF-7 — seuls les octets > 0x7F le sont — et
    # quote_mailbox encadre le nom pour le protocole). Les noms non-ASCII
    # arrivent en mUTF-7 via LIST et ne pourraient pas être comparés
    # exactement — fail-closed au chargement.
    _require(all(0x20 <= ord(c) < 0x7F for c in folder),
             f"destination non-ASCII non supportée en V1 (mUTF-7): {folder!r}")
    # espaces en tête/queue interdits : source classique d'erreur de comparaison
    _require(folder == folder.strip(),
             f"espaces en tête/queue interdits dans l'allowlist: {folder!r}")
    if destination_is_forbidden(folder):
        raise ConfigError(
            f"Destination interdite dans l'allowlist (Corbeille/Spam/brouillons interdits): {folder!r}"
        )


def _validate_config(data: dict) -> dict:
    _require(isinstance(data, dict), "config.json doit être un objet")
    for key in ("account", "source", "destinations", "writes"):
        _require(key in data, f"section manquante: {key}")

    account = data["account"]
    _require(isinstance(account, dict), "account doit être un objet")
    _require(account.get("host"), "account.host requis")
    port = account.get("port", 993)
    _require(isinstance(port, int) and 1 <= port <= 65535, "account.port invalide")
    _require(account.get("password_env"), "account.password_env requis (nom de variable .env)")
    account.setdefault("login_env", "MAIL_TRIAGE_IMAP_LOGIN")

    source = data["source"]
    _require(isinstance(source, dict) and source.get("mailbox"), "source.mailbox requis")
    # V1 fail-closed : seule INBOX est une source supportée. Un plan construit
    # sur une autre boîte déplacerait des UIDs interprétés dans le mauvais
    # contexte si uid_move ne sélectionnait pas exactement la même boîte.
    _require(source.get("mailbox") == "INBOX",
             "source.mailbox doit être 'INBOX' en V1 (sécurité UID context)")

    dest = data["destinations"]
    _require(isinstance(dest, dict) and isinstance(dest.get("allowlist"), list), "destinations.allowlist requise")
    _require(len(dest["allowlist"]) > 0, "allowlist vide: aucune destination autorisée")
    for folder in dest["allowlist"]:
        _validate_destination(folder)
    dest.setdefault("folders_check", "must_exist")

    writes = data["writes"]
    _require(isinstance(writes, dict), "writes doit être un objet")
    for key in ("enabled", "imap_enabled", "digest_enabled"):
        _require(isinstance(writes.get(key), bool), f"writes.{key} doit être un booléen (kill switch explicite)")

    digest = data.get("digest", {})
    _require(isinstance(digest, dict), "digest doit être un objet")
    digest.setdefault("enabled", False)
    digest.setdefault("lookback_hours", 18)
    digest.setdefault("always_inbox_cap", 10)
    digest.setdefault("min_interval_hours", 20)
    digest.setdefault("scan_recent_uid_window", 300)
    digest.setdefault("sensitive_subject_patterns", [])
    digest.setdefault("timezone", "Europe/Paris")
    _require(isinstance(digest["sensitive_subject_patterns"], list), "digest.sensitive_subject_patterns doit être une liste")
    _require(isinstance(digest["timezone"], str) and digest["timezone"], "digest.timezone doit être une chaîne")
    enrichment = digest.get("enrichment")
    if enrichment is None:
        enrichment = {}
    _require(isinstance(enrichment, dict), "digest.enrichment doit être un objet")
    # V4.1 : lecture bornée du début du corps (invariant révisé, cf. ARCHITECTURE §10).
    # Off par défaut : déploiement initial avec publication des extraits désactivée.
    enrichment.setdefault("enabled", False)
    # notifications auto triables : lecture informative seulement si allowlist explicite
    enrichment.setdefault("gitlab_enrich", False)
    enrichment.setdefault("max_fetch_bytes", 4096)
    enrichment.setdefault("max_preview_chars", 180)
    _require(isinstance(enrichment["enabled"], bool), "digest.enrichment.enabled doit être un booléen")
    _require(isinstance(enrichment["gitlab_enrich"], bool), "digest.enrichment.gitlab_enrich doit être un booléen")
    _require(isinstance(enrichment["max_fetch_bytes"], int) and 512 <= enrichment["max_fetch_bytes"] <= 65536,
             "digest.enrichment.max_fetch_bytes doit être un int entre 512 et 65536")
    _require(isinstance(enrichment["max_preview_chars"], int) and 60 <= enrichment["max_preview_chars"] <= 500,
             "digest.enrichment.max_preview_chars doit être un int entre 60 et 500")
    digest["enrichment"] = enrichment
    data["digest"] = digest

    kchat = data.get("kchat", {})
    _require(isinstance(kchat, dict), "kchat doit être un objet")
    kchat.setdefault("base_url", "https://infomaniak.kchat.infomaniak.com/api/v4")
    kchat.setdefault("token_env", "MAIL_TRIAGE_KCHAT_TOKEN")
    _require(kchat.get("token_env"), "kchat.token_env requis")
    kchat.setdefault("dm_username_env", "MAIL_TRIAGE_KCHAT_DM_USERNAME")
    kchat.setdefault("timeout_seconds", 15)
    data["kchat"] = kchat

    interactive = data.get("interactive", {})
    _require(isinstance(interactive, dict), "interactive doit être un objet")
    # Canal interactif MP (ARCHITECTURE §11) : lecture interactive OFF par défaut ;
    # les mutations interactives auront leurs propres gates séparés (J4).
    interactive.setdefault("enabled", False)
    _require(isinstance(interactive.get("enabled"), bool),
             "interactive.enabled doit être un booléen")
    data["interactive"] = interactive

    plan = data.get("plan", {})
    plan.setdefault("expire_hours", 24)
    data["plan"] = plan

    return data


KNOWN_MATCH_KEYS = ("from_any", "from_domain_any", "subject_any", "to_contains_any")


def _validate_match_list(rule_id: str, match: dict) -> None:
    """Chaque clé de match : liste de chaînes non vides (une string serait itérée
    caractère par caractère par any() → fausse positive massive)."""
    for key, value in match.items():
        _require(key in KNOWN_MATCH_KEYS, f"règle {rule_id}: clé de match inconnue: {key}")
        _require(isinstance(value, list) and value,
                 f"règle {rule_id}: {key} doit être une liste non vide de chaînes")
        _require(all(isinstance(v, str) and v.strip() for v in value),
                 f"règle {rule_id}: {key} ne doit contenir que des chaînes non vides")


def load_rules(config_dir_path: Path) -> dict:
    """rules.json privé : {rules: [...], sensitive_senders: [...]} — validation stricte."""
    path = config_dir_path / "rules.json"
    if not path.exists():
        return {"rules": [], "sensitive_senders": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"rules.json illisible: {exc}") from exc
    _require(isinstance(data, dict) and isinstance(data.get("rules"), list), "rules.json: rules doit être une liste")
    ids = set()
    for rule in data["rules"]:
        _require(isinstance(rule, dict) and rule.get("id"), "règle sans id")
        _require(rule["id"] not in ids, f"id de règle dupliqué: {rule['id']}")
        ids.add(rule["id"])
        _require(rule.get("mode") in ("auto", "propose", "never"), f"règle {rule['id']}: mode invalide (auto|propose|never)")
        _require(isinstance(rule.get("match"), dict), f"règle {rule['id']}: match requis")
        _validate_match_list(rule["id"], rule["match"])
        if rule["mode"] in ("auto", "propose"):
            _require(rule.get("folder"), f"règle {rule['id']}: folder requis pour mode {rule['mode']}")
            if rule.get("folder"):
                _validate_destination(rule["folder"])
        _require(isinstance(rule.get("priority", 100), int), f"règle {rule['id']}: priority doit être un entier")
    data.setdefault("sensitive_senders", [])
    _require(isinstance(data["sensitive_senders"], list)
             and all(isinstance(v, str) and v.strip() for v in data["sensitive_senders"]),
             "sensitive_senders doit être une liste de chaînes non vides")
    return data


def load(config_dir_path: Path) -> dict:
    """Charge config.json (fail-closed) + rules.json. Ne lit jamais les secrets ici."""
    path = config_dir_path / "config.json"
    if not path.exists():
        raise ConfigError(f"config.json introuvable: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"config.json illisible: {exc}") from exc
    data = _validate_config(data)
    data["rules"] = load_rules(config_dir_path)
    data["_config_dir"] = str(config_dir_path)
    return data


def ensure_private_dir(path: Path) -> None:
    """Crée le répertoire privé 0700 (umask 077 au démarrage du moteur)."""
    old_umask = os.umask(0o077)
    try:
        path.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(old_umask)
    os.chmod(path, stat.S_IRWXU)


def assert_private_file(path: Path) -> None:
    """Vérifie qu'un fichier d'état privé n'est pas lisible par le groupe/autres."""
    if not path.exists():
        return
    mode = path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
