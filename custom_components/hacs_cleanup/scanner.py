"""
Scan-Logik für HACS Cleanup.
Liest HA-Storage-Dateien und findet verwaiste Einträge.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


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


def _get_hacs_repo_ids(storage_dir: Path) -> tuple[set[str], str]:
    """
    Liest alle bekannten Repo-IDs aus hacs.repositories.
    Struktur: {"version":1, "data": {"REPO_ID": {...}, ...}}
    Gibt (repo_id_set, status_text) zurück.
    """
    path = storage_dir / "hacs.repositories"
    data, _ = _load(path)
    if not data:
        return set(), f"WARNUNG: {path.name} nicht gefunden"

    repos = data.get("data", {})
    if not isinstance(repos, dict) or not repos:
        return set(), f"WARNUNG: Unerwartete Struktur in {path.name}"

    ids = {str(k) for k in repos.keys()}
    return ids, f"{path.name}: {len(ids)} Repos bekannt"


def _get_hacs_entry_id(config_entries: list) -> str:
    for e in config_entries:
        if e.get("domain") == "hacs":
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
    hacs_repo_ids, hacs_status = _get_hacs_repo_ids(storage_dir)
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
    w(f"HACS Entry-ID     : {hacs_entry_id or 'nicht gefunden'}")
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
    orphaned_devices = [
        d for d in devices
        if d.get("config_entries")
        and not set(d["config_entries"]).intersection(valid_entry_ids)
    ]
    findings += len(orphaned_devices)

    w(f"--- 2. Verwaiste Geräte (config_entry_id fehlt): {len(orphaned_devices)} ---")
    if orphaned_devices:
        for d in orphaned_devices:
            dev_id  = d.get("id", "?")
            name    = d.get("name_by_user") or d.get("name") or "?"
            ces     = d.get("config_entries", [])
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
    if hacs_entry_id and hacs_repo_ids:
        for d in devices:
            if hacs_entry_id not in d.get("config_entries", []):
                continue
            for ident in d.get("identifiers", []):
                if (isinstance(ident, list) and len(ident) == 2
                        and ident[0] == "hacs"
                        and str(ident[1]).isdigit()
                        and str(ident[1]) not in hacs_repo_ids):
                    orphaned_hacs_devices.append((d, str(ident[1])))
                    break
    findings += len(orphaned_hacs_devices)

    w(f"--- 3. Verwaiste HACS-Geräte (Repo nicht mehr in hacs.repositories): "
      f"{len(orphaned_hacs_devices)} ---")
    if not hacs_entry_id:
        w("  HINWEIS: HACS Entry-ID nicht gefunden – Abschnitt übersprungen")
    elif not hacs_repo_ids:
        w("  HINWEIS: hacs.repositories nicht lesbar – Abschnitt übersprungen")
    elif orphaned_hacs_devices:
        for d, repo_id in orphaned_hacs_devices:
            dev_id  = d.get("id", "?")
            name    = d.get("name_by_user") or d.get("name") or "?"
            mfr     = d.get("manufacturer", "?")
            line_no = _find_line(device_lines, f'"id": "{dev_id}"')
            w(f"  Datei  : {DEVICE_FILE}")
            w(f"  Zeile  : {line_no if line_no > 0 else 'nicht ermittelbar'}")
            w(f"  Eintrag: {name}  [manufacturer={mfr}, repo_id={repo_id}]")
            w(f"  Grund  : Repo-ID {repo_id} nicht mehr in hacs.repositories")
            w(f"  Aktion : Zeile aus {DEVICE_FILE.name} löschen + HA neu starten")
            w()
    else:
        w("  OK – Keine gefunden")
    w()

    # ── 4. Verwaiste HACS-Entitäten ───────────────────────────────────────────
    orphaned_hacs_entities: list[tuple] = []
    if hacs_repo_ids:
        for e in entities:
            if e.get("platform") != "hacs":
                continue
            uid = str(e.get("unique_id", ""))
            if uid and uid.isdigit() and uid not in hacs_repo_ids:
                orphaned_hacs_entities.append((e, uid))
    findings += len(orphaned_hacs_entities)

    w(f"--- 4. Verwaiste HACS-Entitäten (Repo nicht mehr in hacs.repositories): "
      f"{len(orphaned_hacs_entities)} ---")
    if not hacs_repo_ids:
        w("  HINWEIS: hacs.repositories nicht lesbar – Abschnitt übersprungen")
    elif orphaned_hacs_entities:
        for e, uid in orphaned_hacs_entities:
            eid     = e.get("entity_id", "?")
            line_no = _find_line(entity_lines, f'"entity_id": "{eid}"')
            w(f"  Datei  : {ENTITY_FILE}")
            w(f"  Zeile  : {line_no if line_no > 0 else 'nicht ermittelbar'}")
            w(f"  Eintrag: {eid}  [platform=hacs, unique_id={uid}]")
            w(f"  Grund  : Repo-ID {uid} nicht mehr in hacs.repositories")
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
