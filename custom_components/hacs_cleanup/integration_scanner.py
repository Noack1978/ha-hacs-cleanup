"""
Scan-Logik für ungenutzte HACS Integration-Repos (custom_components).

Vergleicht die installierten HACS-Integration-Repos (Kategorie "integration")
mit tatsächlich eingerichteten Integrationen. Eine Integration gilt als
genutzt, wenn ihre Domain entweder

1. als Config Entry eingerichtet ist (core.config_entries – der Normalfall
   für praktisch alle modernen Integrationen, UI- wie YAML-basiert importiert)
2. oder in einer YAML-Datei im Konfigurationsordner referenziert wird – als
   Top-Level-Schlüssel (z.B. "waste_collection_schedule:") oder als
   "platform: <domain>" innerhalb einer Plattform-Liste (z.B. sensor:).
   Deckt die wenigen Integrationen ab, die ausschließlich per YAML und ohne
   Config Entry funktionieren.

Die Domain eines Repos wird primär aus hacs.repositories ("domain"-Feld)
gelesen; falls dort nicht vorhanden, wird ersatzweise der aus full_name
abgeleitete Ordnername unter custom_components/ geprüft.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

# Top-Level-YAML-Schlüssel einer Domain, z.B. "waste_collection_schedule:"
# am Zeilenanfang (kein Einrückung), gefolgt von ':' und optional einem Kommentar.
TOPLEVEL_KEY_RE_TEMPLATE = r"(?m)^{domain}:\s*(#.*)?$"

# "platform: <domain>" innerhalb einer Plattform-Liste (sensor:, binary_sensor:, ...),
# mit oder ohne Anführungszeichen.
PLATFORM_RE_TEMPLATE = r"(?m)^\s*platform:\s*['\"]?{domain}['\"]?\s*(#.*)?$"

# Ordner, die beim YAML-Scan übersprungen werden (keine HA-Konfiguration).
SKIP_DIR_NAMES = {".storage", "custom_components", "www", "themes", "blueprints", "__pycache__", ".cloud"}


def _load(path: Path) -> dict:
    """Lädt eine JSON-Datei. Gibt {} zurück, wenn nicht vorhanden/ungültig."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        return {}


def _is_installed(repo: dict) -> bool:
    """Prüft, ob ein Repo tatsächlich installiert ist (nicht nur im Katalog bekannt)."""
    if repo.get("installed") is True:
        return True
    if repo.get("installed_version") or repo.get("version_installed"):
        return True
    return False


def _resolve_domain(repo: dict, custom_components_dir: Path) -> str | None:
    """Ermittelt die Domain (=Ordnername unter custom_components/) eines
    Integration-Repos. Primär aus hacs.repositories, ersatzweise über den
    aus full_name abgeleiteten Ordnernamen."""
    domain = repo.get("domain")
    if domain:
        return str(domain)

    full_name = repo.get("full_name") or ""
    repo_short = full_name.split("/")[-1] if "/" in full_name else full_name
    if not repo_short:
        return None

    # Übliche Namensvarianten durchprobieren (Bindestrich -> Unterstrich, ha-Präfix entfernen)
    candidates = [repo_short, repo_short.replace("-", "_")]
    for prefix in ("ha-", "ha_", "home-assistant-", "homeassistant-"):
        if repo_short.startswith(prefix):
            candidates.append(repo_short[len(prefix):].replace("-", "_"))

    for candidate in candidates:
        if (custom_components_dir / candidate / "manifest.json").is_file():
            return candidate

    return None


def _get_integration_repos(storage_dir: Path) -> tuple[list[dict], str]:
    """Liest alle INSTALLIERTEN Integration-Repos aus hacs.repositories.

    hacs.repositories enthält den kompletten HACS-Katalog, nicht nur
    installierte Repos – daher zusätzlich Filterung auf "installed".
    """
    path = storage_dir / "hacs.repositories"
    data = _load(path)
    if not data:
        return [], f"WARNUNG: {path.name} nicht gefunden"

    repos = data.get("data", {})
    if not isinstance(repos, dict) or not repos:
        return [], f"WARNUNG: Unerwartete Struktur in {path.name}"

    custom_components_dir = storage_dir.parent / "custom_components"

    integrations = []
    for repo_id, repo in repos.items():
        if not isinstance(repo, dict) or repo.get("category") != "integration":
            continue
        if not _is_installed(repo):
            continue
        domain = _resolve_domain(repo, custom_components_dir)
        integrations.append(
            {
                "id": str(repo_id),
                "full_name": repo.get("full_name", "?"),
                "name": repo.get("name") or repo.get("full_name", "?"),
                "domain": domain,
            }
        )
    return integrations, (
        f"{path.name}: {len(repos)} Repos im Katalog, {len(integrations)} davon "
        f"installiert (Kategorie integration)"
    )


def get_installed_integration_repos(storage_dir_str: str) -> list[dict]:
    """Öffentlicher Zugriff auf die installierten Integration-Repos, z.B. für
    den Options-Flow (Repo-Auswahl für den Ausschluss). Wird im Executor
    ausgeführt (kein async).

    Args:
        storage_dir_str: Pfad zu .storage/ (z.B. /config/.storage)

    Returns:
        Liste von {"id", "full_name", "name", "domain"}, sortiert nach Name.
    """
    integrations, _ = _get_integration_repos(Path(storage_dir_str))
    return sorted(integrations, key=lambda p: p["name"].lower())


def _get_config_entry_domains(storage_dir: Path) -> set[str]:
    """Liest alle Domains, für die ein Config Entry existiert."""
    data = _load(storage_dir / "core.config_entries")
    entries = data.get("data", {}).get("entries", [])
    return {e.get("domain") for e in entries if isinstance(e, dict) and e.get("domain")}


def _get_yaml_files(config_dir: Path) -> list[Path]:
    """Sammelt alle .yaml/.yml-Dateien im Konfigurationsordner (rekursiv),
    ohne HA-interne/Nicht-Konfigurationsordner (.storage, custom_components,
    www, themes, blueprints)."""
    files: list[Path] = []
    try:
        for path in config_dir.rglob("*.y*ml"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(config_dir).parts[:-1]):
                continue
            files.append(path)
    except OSError:
        pass
    return files


def _get_yaml_referenced_domains(config_dir: Path, yaml_files: list[Path]) -> set[str]:
    """Liest alle YAML-Dateien im Konfigurationsordner und sammelt Domains,
    die entweder als Top-Level-Schlüssel oder als 'platform: <domain>'
    referenziert werden. Reiner Text-Scan (kein YAML-Parser), um robust
    gegen Custom-Tags (!include, !secret, ...) zu sein, die ein Standard-
    YAML-Parser ohne HA-Loader nicht auflösen kann."""
    all_text = ""
    for yaml_file in yaml_files:
        try:
            all_text += "\n" + yaml_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

    found: set[str] = set()
    for match in re.finditer(r"(?m)^([a-z][a-z0-9_]*):\s*(#.*)?$", all_text):
        found.add(match.group(1))
    for match in re.finditer(r"(?m)^\s*platform:\s*['\"]?([a-z][a-z0-9_]*)['\"]?\s*(#.*)?$", all_text):
        found.add(match.group(1))
    return found


def run_scan_unused_integrations(
    storage_dir_str: str,
    report_path_str: str,
    excluded_ids: list[str] | None = None,
) -> dict:
    """
    Vergleicht installierte HACS-Integration-Repos mit tatsächlich
    eingerichteten Integrationen (Config Entries bzw. YAML-Referenzen).

    Wird im Executor ausgeführt (kein async).

    Args:
        storage_dir_str: Pfad zu .storage/ (z.B. /config/.storage)
        report_path_str: Pfad für den Vollbericht
        excluded_ids: Repo-IDs, die manuell von der Prüfung ausgeschlossen werden

    Returns:
        {"notification": str, "report": str, "used_count": int, "unused_count": int}
    """
    storage_dir = Path(storage_dir_str)
    report_path = Path(report_path_str)
    config_dir = storage_dir.parent
    excluded_id_set = set(excluded_ids or [])

    all_integrations, status = _get_integration_repos(storage_dir)
    excluded = [p for p in all_integrations if p["id"] in excluded_id_set]
    integrations = [p for p in all_integrations if p["id"] not in excluded_id_set]

    config_entry_domains = _get_config_entry_domains(storage_dir)
    yaml_files = _get_yaml_files(config_dir)
    yaml_domains = _get_yaml_referenced_domains(config_dir, yaml_files)

    lines_out: list[str] = []

    def w(text: str = "") -> None:
        lines_out.append(text)

    w(f"=== HACS Cleanup – Ungenutzte Integrationen-Scan – {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===")
    w()
    w(f"Installierte Integration-Repos: {len(all_integrations)}  ({status})")
    if excluded:
        w(f"Davon manuell ausgeschlossen: {len(excluded)} (siehe unten) – geprüft werden {len(integrations)}")
    w(f"Config Entries gesamt: {len(config_entry_domains)} Domains")
    w(f"Gescannte YAML-Dateien: {len(yaml_files)}")
    w()
    w("HINWEIS: Eine Integration gilt als genutzt, wenn ihre Domain entweder als")
    w("Config Entry eingerichtet ist (Normalfall) oder in einer YAML-Datei im")
    w("Konfigurationsordner referenziert wird (Top-Level-Schlüssel oder")
    w("'platform: <domain>'). Kann die Domain eines Repos nicht ermittelt werden")
    w("(z.B. weil der custom_components-Ordner nicht dem üblichen Namensschema")
    w("folgt), wird dies im Bericht vermerkt – hier vor dem Entfernen unbedingt")
    w("manuell prüfen.")
    w()

    used: list[dict] = []
    unused: list[dict] = []
    unresolved: list[dict] = []

    for repo in integrations:
        domain = repo.get("domain")
        if not domain:
            unresolved.append(repo)
            continue
        via_config_entry = domain in config_entry_domains
        via_yaml = domain in yaml_domains
        entry = {**repo, "via_config_entry": via_config_entry, "via_yaml": via_yaml}
        (used if (via_config_entry or via_yaml) else unused).append(entry)

    w(f"--- Vermutlich GENUTZT ({len(used)}) ---")
    if used:
        for r in used:
            via = []
            if r["via_config_entry"]:
                via.append("Config Entry")
            if r["via_yaml"]:
                via.append("YAML")
            w(f"  {r['name']}  [{r['full_name']}]  Domain: {r['domain']}  ({', '.join(via)})")
        w()
    else:
        w("  Keine")
        w()

    w(f"--- Vermutlich UNGENUTZT ({len(unused)}) ---")
    if unused:
        for r in unused:
            w(f"  {r['name']}  [{r['full_name']}]  Domain: {r['domain']}  repo_id={r['id']}")
            w(f"    Kein Config Entry und keine YAML-Referenz für Domain '{r['domain']}' gefunden.")
        w()
    else:
        w("  Keine – alle installierten Integrationen scheinen genutzt zu werden.")
        w()

    if unresolved:
        w(f"--- Domain nicht ermittelbar ({len(unresolved)}) ---")
        w("Für diese Repos konnte keine Domain bestimmt werden (weder aus")
        w("hacs.repositories noch über einen passenden custom_components-Ordner).")
        w("Manuell prüfen, ob die Integration genutzt wird.")
        for r in unresolved:
            w(f"  {r['name']}  [{r['full_name']}]  repo_id={r['id']}")
        w()

    if excluded:
        w(f"--- Manuell ausgeschlossen ({len(excluded)}) ---")
        w("Diese Repos wurden in der Integrationskonfiguration ausgeschlossen")
        w("und nicht geprüft.")
        for r in sorted(excluded, key=lambda p: p["name"].lower()):
            w(f"  {r['name']}  [{r['full_name']}]")
        w()

    w("--- Zusammenfassung ---")
    w(f"Genutzt              : {len(used)}")
    w(f"Ungenutzt            : {len(unused)}")
    if unresolved:
        w(f"Domain nicht ermittelbar: {len(unresolved)}")
    if excluded:
        w(f"Ausgeschlossen       : {len(excluded)}")

    report_text = "\n".join(lines_out)

    try:
        report_path.write_text(report_text, encoding="utf-8")
    except OSError:
        pass

    notif_lines = [
        f"Geprüfte Integration-Repos: {len(integrations)}",
        f"Vermutlich ungenutzt: {len(unused)}",
    ]
    if unresolved:
        notif_lines.append(f"Domain nicht ermittelbar: {len(unresolved)}")
    if unused:
        notif_lines.append("")
        notif_lines.extend(f"• {r['name']}" for r in unused[:10])
        if len(unused) > 10:
            notif_lines.append(f"… und {len(unused) - 10} weitere")
    notif_lines.append("")
    notif_lines.append(f"→ Details im Vollbericht: {report_path}")

    return {
        "notification": "\n".join(notif_lines),
        "report": report_text,
        "used_count": len(used),
        "unused_count": len(unused),
    }
