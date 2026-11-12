"""
Scan-Logik für HACS Cleanup.
Liest HA-Storage-Dateien und findet verwaiste Einträge.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .repo_store import MANAGER_DOMAINS, load_repositories


def _load(path: Path) -> tuple[dict, list[str]]:
    """Lädt eine JSON-Datei und gibt (dict, zeilenliste) zurück."""
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw), raw.splitlines()
    except FileNotFoundError:
        return {}, []
    except Exception:  # noqa: BLE001
        return {}, []


def _find_line(lines: list[str], *terms: str) -> int:
    """Erste Zeile (1-basiert) die ALLE terms enthält. -1 = nicht gefunden."""
    for i, line in enumerate(lines, 1):
        if all(t in line for t in terms):
            return i
    return -1


def _get_hacs_repo_ids(storage_dir: Path) -> tuple[set[str], str, str]:
    """
    Liest alle bekannten Repo-IDs aus der Repository-Datei von HACS
    (hacs.repositories, bis HA 2026.10) bzw. dem Marketplace
    (marketplace.repositories, ab HA 2026.11).
    Struktur: {"version":1, "data": {"REPO_ID": {...}, ...}}
    Gibt (repo_id_set, status_text, dateiname) zurück.
    """
    repos, source = load_repositories(storage_dir)
    if not repos:
        return set(), source, "der Repository-Datei"

    ids = {str(k) for k in repos.keys()}
    return ids, f"{source}: {len(ids)} Repos bekannt", source


def _get_hacs_entry_id(config_entries: list) -> str:
    """Config-Entry-ID von HACS ("hacs") bzw. dem Marketplace ("marketplace")."""
    for domain in MANAGER_DOMAINS:
        for e in config_entries:
            if e.get("domain") == domain:
                return e.get("entry_id", "")
    return ""


def run_scan(storage_dir_str: str, report_path_str: str) -> dict:
    """
    Führt den kompletten Scan durch.
    Wird im Executor ausgeführt (kein async).

    Args:
        storage_dir_str: Pfad zu .storage/ (z.B. /config/.storage)
        report_path_str: Pfad für den Vollbericht (z.B. /config/hacs_cleanup_report.txt)

    Returns:
        {
            "notification": str,   # Kurztext für Persistent Notification
            "report": str,         # Vollständiger Bericht
            "findings": int,       # Anzahl Funde gesamt
        }
    """
    storage_dir = Path(storage_dir_str)
    report_path = Path(report_path_str)

    ENTITY_FILE  = storage_dir / "core.entity_registry"
    DEVICE_FILE  = storage_dir / "core.device_registry"
    ENTRIES_FILE = storage_dir / "core.config_entries"

    entity_data,  entity_lines  = _load(ENTITY_FILE)
    device_data,  device_lines  = _load(DEVICE_FILE)
    entries_data, entries_lines = _load(ENTRIES_FILE)

    entities       = entity_data .get("data", {}).get("entities", [])
    devices        = device_data .get("data", {}).get("devices",  [])
    config_entries = entries_data.get("data", {}).get("entries",  [])

    valid_entry_ids = {e.get("entry_id") for e in config_entries} - {None}
    hacs_repo_ids, hacs_status, repo_file = _get_hacs_repo_ids(storage_dir)
    hacs_entry_id = _get_hacs_entry_id(config_entries)

    lines_out = []

    def w(text: str = "") -> None:
        lines_out.append(text)

    w(f"=== HACS Cleanup Scan – {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===")
    w()
    w(f"Entitäten gesamt  : {len(entities)}")
    w(f"Geräte gesamt     : {len(devices)}")
    w(f"Config-Einträge   : {len(config_entries)}")
    w(f"HACS Repos bekannt: {len(hacs_repo_ids)}  ({hacs_status})")
    w(f"HACS/Marketplace Entry-ID: {hacs_entry_id or 'nicht gefunden'}")
    w()

    findings = 0

    # ── 1. Verwaiste Entitäten ─────────────────────────────────────────────────
    orphaned_entities = [
        e for e in entities
        if e.get("config_entry_id")
        and e["config_entry_id"] not in valid_entry_ids
    ]
    findings += len(orphaned_entities)

    w(f"--- 1. Verwaiste Entitäten (config_entry_id fehlt): {len(orphaned_entities)} ---")
    if orphaned_entities:
        for e in orphaned_entities:
            eid     = e.get("entity_id", "?")
            plat    = e.get("platform", "?")
            ceid    = e.get("config_entry_id", "?")
            line_no = _find_line(entity_lines, f'"entity_id": "{eid}"')
            w(f"  Datei  : {ENTITY_FILE}")
            w(f"  Zeile  : {line_no if line_no > 0 else 'nicht ermittelbar'}")
            w(f"  Eintrag: {eid}")
            w(f"  Grund  : platform={plat}, config_entry_id={ceid} existiert nicht mehr")
            w()
    else:
        w("  OK – Keine gefunden")
    w()

    # ── 2. Verwaiste Geräte ────────────────────────────────────────────────────
    def _device_entry_ids(d: dict) -> list:
        """Liefert Config-Entry-IDs – unterstützt neues (config_entry_id) und altes (config_entries) Schema."""
        if d.get("config_entry_id"):
            return [d["config_entry_id"]]
        return d.get("config_entries", [])

    orphaned_devices = [
        d for d in devices
        if not d.get("parent_device_id")  # Child Devices überspringen
        and _device_entry_ids(d)
        and not set(_device_entry_ids(d)).intersection(valid_entry_ids)
    ]
    findings += len(orphaned_devices)

    w(f"--- 2. Verwaiste Geräte (config_entry_id fehlt): {len(orphaned_devices)} ---")
    if orphaned_devices:
        for d in orphaned_devices:
            dev_id  = d.get("id", "?")
            name    = d.get("name_by_user") or d.get("name") or "?"
            ces     = _device_entry_ids(d)
            line_no = _find_line(device_lines, f'"id": "{dev_id}"')
            w(f"  Datei  : {DEVICE_FILE}")
            w(f"  Zeile  : {line_no if line_no > 0 else 'nicht ermittelbar'}")
            w(f"  Eintrag: {name}  [id={dev_id}]")
            w(f"  Grund  : config_entries={ces} → alle ungültig")
            w()
    else:
        w("  OK – Keine gefunden")
    w()

    # ── 3. Verwaiste HACS-Geräte ───────────────────────────────────────────────
    orphaned_hacs_devices: list[tuple] = []
    orphaned_device_ids = {d.get("id") for d in orphaned_devices}
    if hacs_repo_ids:
        for d in devices:
            if d.get("parent_device_id"):
                continue  # Child Device – wird über Parent verwaltet
            if d.get("id") in orphaned_device_ids:
                continue  # bereits in Abschnitt 2 erfasst
            # Ist der Config Entry bekannt, nur dessen Geräte prüfen. Ohne
            # Config Entry (z.B. falls der Marketplace keinen anlegt) greift
            # allein der Geräte-Identifier.
            if hacs_entry_id and hacs_entry_id not in _device_entry_ids(d):
                continue
            for ident in d.get("identifiers", []):
                if (isinstance(ident, (list, tuple)) and len(ident) == 2
                        and ident[0] in MANAGER_DOMAINS
                        and str(ident[1]).isdigit()
                        and str(ident[1]) not in hacs_repo_ids):
                    orphaned_hacs_devices.append((d, str(ident[1])))
                    break
    findings += len(orphaned_hacs_devices)

    w(f"--- 3. Verwaiste HACS-Geräte (Repo nicht mehr in {repo_file}): "
      f"{len(orphaned_hacs_devices)} ---")
    if not hacs_repo_ids:
        w("  HINWEIS: Repository-Datei nicht lesbar – Abschnitt übersprungen")
    elif orphaned_hacs_devices:
        for d, repo_id in orphaned_hacs_devices:
            dev_id  = d.get("id", "?")
            name    = d.get("name_by_user") or d.get("name") or "?"
            mfr     = d.get("manufacturer", "?")
            line_no = _find_line(device_lines, f'"id": "{dev_id}"')
            w(f"  Datei  : {DEVICE_FILE}")
            w(f"  Zeile  : {line_no if line_no > 0 else 'nicht ermittelbar'}")
            w(f"  Eintrag: {name}  [manufacturer={mfr}, repo_id={repo_id}]")
            w(f"  Grund  : Repo-ID {repo_id} nicht mehr in {repo_file}")
            w(f"  Aktion : Zeile aus {DEVICE_FILE.name} löschen + HA neu starten")
            w()
    else:
        w("  OK – Keine gefunden")
    w()

    # ── 4. Verwaiste HACS-Entitäten ───────────────────────────────────────────
    orphaned_hacs_entities: list[tuple] = []
    if hacs_repo_ids:
        for e in entities:
            if e.get("platform") not in MANAGER_DOMAINS:
                continue
            uid = str(e.get("unique_id", ""))
            if uid and uid.isdigit() and uid not in hacs_repo_ids:
                orphaned_hacs_entities.append((e, uid))
    findings += len(orphaned_hacs_entities)

    w(f"--- 4. Verwaiste HACS-Entitäten (Repo nicht mehr in {repo_file}): "
      f"{len(orphaned_hacs_entities)} ---")
    if not hacs_repo_ids:
        w("  HINWEIS: Repository-Datei nicht lesbar – Abschnitt übersprungen")
    elif orphaned_hacs_entities:
        for e, uid in orphaned_hacs_entities:
            eid     = e.get("entity_id", "?")
            line_no = _find_line(entity_lines, f'"entity_id": "{eid}"')
            w(f"  Datei  : {ENTITY_FILE}")
            w(f"  Zeile  : {line_no if line_no > 0 else 'nicht ermittelbar'}")
            w(f"  Eintrag: {eid}  [platform={e.get('platform')}, unique_id={uid}]")
            w(f"  Grund  : Repo-ID {uid} nicht mehr in {repo_file}")
            w(f"  Aktion : Zeile aus {ENTITY_FILE.name} löschen + HA neu starten")
            w()
    else:
        w("  OK – Keine gefunden")
    w()

    # ── Zusammenfassung ────────────────────────────────────────────────────────
    w("--- Zusammenfassung ---")
    w(f"Verwaiste Entitäten      : {len(orphaned_entities)}")
    w(f"Verwaiste Geräte         : {len(orphaned_devices)}")
    w(f"Verwaiste HACS-Geräte    : {len(orphaned_hacs_devices)}")
    w(f"Verwaiste HACS-Entitäten : {len(orphaned_hacs_entities)}")
    w(f"Gesamt                   : {findings}")
    if findings == 0:
        w("✓ Alles sauber.")
    else:
        w(f"→ Details im Vollbericht: {report_path}")

    report_text = "\n".join(lines_out)

    # Vollbericht schreiben
    try:
        report_path.write_text(report_text, encoding="utf-8")
    except OSError:
        pass

    # Kurzfassung für Notification
    notif_lines = [
        f"HACS Repos: {len(hacs_repo_ids)} bekannt",
        f"Verwaiste Entitäten      : {len(orphaned_entities)}",
        f"Verwaiste Geräte         : {len(orphaned_devices)}",
        f"Verwaiste HACS-Geräte    : {len(orphaned_hacs_devices)}",
        f"Verwaiste HACS-Entitäten : {len(orphaned_hacs_entities)}",
        "",
        "✓ Alles sauber." if findings == 0 else f"→ {findings} Funde. Vollbericht: {report_path}",
    ]

    return {
        "notification": "\n".join(notif_lines),
        "report": report_text,
        "findings": findings,
    }
