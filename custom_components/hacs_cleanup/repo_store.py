"""
Gemeinsamer Zugriff auf die Repository-Daten von HACS bzw. dem Marketplace.

Ab Home Assistant 2026.11 ist HACS als "Marketplace" fester Bestandteil des
Cores. Dabei ändern sich für diese Integration drei Dinge:

1. Die Storage-Datei heißt nicht mehr ".storage/hacs.repositories", sondern
   ".storage/marketplace.repositories" (in Vorabständen des Cores zeitweise
   ".storage/store.repositories").
2. Die Domain der Integration (Config Entry, Geräte-Identifier, Plattform der
   Entitäten) ist nicht mehr "hacs", sondern "marketplace".
3. Verzeichnisse (custom_components/, www/community/) und die Kategorien
   ("integration", "plugin") bleiben unverändert.

Dieses Modul kapselt alles davon, damit die Scanner vor UND nach 2026.11
funktionieren, ohne selbst Dateinamen oder Domains zu kennen.
"""

from __future__ import annotations

import json
from pathlib import Path

# Mögliche Storage-Dateien, in Prioritätsreihenfolge (neu -> alt).
REPOSITORY_FILES: tuple[str, ...] = (
    "marketplace.repositories",  # Home Assistant 2026.11 und neuer
    "store.repositories",        # Zwischenstand der Core-Entwicklung
    "hacs.repositories",         # HACS bis 2026.10
)

# Domains, unter denen Config Entry, Geräte und Entitäten der Repo-Verwaltung
# registriert sind (neu -> alt).
MANAGER_DOMAINS: tuple[str, ...] = ("marketplace", "hacs")

# Kategorie-Bezeichnungen. "plugin" ist die Kategorie für Lovelace-Karten.
PLUGIN_CATEGORIES: frozenset[str] = frozenset({"plugin", "dashboard"})
INTEGRATION_CATEGORIES: frozenset[str] = frozenset({"integration"})


def _load(path: Path) -> dict:
    """Lädt eine JSON-Datei. Gibt {} zurück, wenn nicht vorhanden/ungültig."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def find_repositories_file(storage_dir: Path) -> Path | None:
    """Wählt die aktuell gültige Repository-Datei.

    Existieren mehrere (z.B. nach der Migration oder nach einem Downgrade),
    gewinnt die zuletzt geänderte; bei gleichem Zeitstempel die neuere
    Bezeichnung laut REPOSITORY_FILES.
    """
    existing: list[tuple[float, int, Path]] = []
    for priority, name in enumerate(REPOSITORY_FILES):
        path = storage_dir / name
        try:
            if path.is_file():
                existing.append((path.stat().st_mtime, -priority, path))
        except OSError:
            continue
    if not existing:
        return None
    return max(existing)[2]


def _extract_repos(payload: object) -> dict[str, dict]:
    """Holt die Repos als {repo_id: repo_dict} aus dem Storage-Inhalt.

    Unterstützt das bekannte Schema {"data": {"<id>": {...}}} sowie – falls
    sich das Format ändert – eine Liste von Objekten mit "id" und eine
    zusätzliche Verschachtelungsebene "repositories".
    """
    if isinstance(payload, dict) and isinstance(payload.get("repositories"), (dict, list)):
        payload = payload["repositories"]

    repos: dict[str, dict] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                repos[str(key)] = value
    elif isinstance(payload, list):
        for value in payload:
            if isinstance(value, dict) and value.get("id") not in (None, ""):
                repos[str(value["id"])] = value
    return repos


def load_repositories(storage_dir: Path) -> tuple[dict[str, dict], str]:
    """Liest alle bekannten Repos (Katalog + installiert).

    Returns:
        ({repo_id: repo_dict}, status_text). Bei Fehlern ist das dict leer
        und der status_text beginnt mit "WARNUNG".
    """
    path = find_repositories_file(storage_dir)
    if path is None:
        names = " / ".join(REPOSITORY_FILES)
        return {}, f"WARNUNG: Keine Repository-Datei gefunden ({names})"

    data = _load(path)
    if not data:
        return {}, f"WARNUNG: {path.name} nicht lesbar"

    repos = _extract_repos(data.get("data"))
    if not repos:
        return {}, f"WARNUNG: Unerwartete Struktur in {path.name}"

    return repos, path.name


def is_installed(repo: dict) -> bool:
    """Prüft, ob ein Repo tatsächlich installiert ist (nicht nur im Katalog)."""
    if repo.get("installed") is True:
        return True
    # Ältere/alternative Schemata verwenden andere Feldnamen
    return bool(repo.get("installed_version") or repo.get("version_installed"))


def category_of(repo: dict) -> str:
    """Kategorie eines Repos als Kleinbuchstaben-String ('' wenn unbekannt)."""
    value = repo.get("category")
    return value.lower() if isinstance(value, str) else ""
