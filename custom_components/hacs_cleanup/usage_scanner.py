"""
Scan-Logik für ungenutzte HACS Plugin-Repos (Lovelace Custom Cards).

Vergleicht die in hacs.repositories installierten Plugin-Repos (Kategorie
"plugin") mit den tatsächlich in den Lovelace-Dashboards (Storage-Modus)
verwendeten `custom:`-Kartentypen.

Primäre Erkennung: Die lokal installierte(n) JS-Datei(en) unter
/config/www/community/<repo>/ werden gelesen und nach
`customElements.define("name", ...)` durchsucht. Das ist der exakte Name,
unter dem eine Karte im Dashboard als `custom:name` ansprechbar ist – jede
gültige Lovelace-Karte muss sich so registrieren, sonst würde HA sie gar
nicht laden.

Fallback (nur falls die JS-Datei nicht gefunden/lesbar ist): Namens-Heuristik
über Datei-/Repo-Namen. In diesem Fall ist ein Fund unsicherer und wird im
Bericht entsprechend gekennzeichnet.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

CUSTOM_PREFIX = "custom:"
DEFINE_RE = re.compile(r"customElements\.define\(\s*['\"`]([a-zA-Z0-9_-]+)['\"`]")


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
    # Ältere/alternative HACS-Schemata verwenden andere Feldnamen
    if repo.get("installed_version") or repo.get("version_installed"):
        return True
    return False


def _get_plugin_repos(storage_dir: Path) -> tuple[list[dict], str]:
    """Liest alle INSTALLIERTEN Plugin-Repos (Lovelace Custom Cards) aus hacs.repositories.

    hacs.repositories enthält bei aktuellem HACS den kompletten bekannten Katalog
    (mehrere tausend Einträge), nicht nur installierte Repos. Für den Vergleich
    "installiert vs. genutzt" muss daher zusätzlich auf "installed" gefiltert werden.
    """
    path = storage_dir / "hacs.repositories"
    data = _load(path)
    if not data:
        return [], f"WARNUNG: {path.name} nicht gefunden"

    repos = data.get("data", {})
    if not isinstance(repos, dict) or not repos:
        return [], f"WARNUNG: Unerwartete Struktur in {path.name}"

    plugins = []
    for repo_id, repo in repos.items():
        if not isinstance(repo, dict) or repo.get("category") != "plugin":
            continue
        if not _is_installed(repo):
            continue
        plugins.append(
            {
                "id": str(repo_id),
                "full_name": repo.get("full_name", "?"),
                "name": repo.get("name") or repo.get("full_name", "?"),
                "file_name": repo.get("file_name"),
            }
        )
    return plugins, f"{path.name}: {len(repos)} Repos im Katalog, {len(plugins)} davon installiert (Kategorie plugin)"


def _heuristic_candidates(repo: dict) -> set[str]:
    """Mögliche Custom-Element-Namen für ein Plugin-Repo – nur Fallback, falls
    die installierte JS-Datei nicht gefunden werden konnte."""
    names: set[str] = set()

    file_name = repo.get("file_name") or ""
    stem = file_name.rsplit("/", 1)[-1]
    if stem.endswith(".js"):
        stem = stem[: -len(".js")]
    if stem:
        names.add(stem.lower())

    full_name = repo.get("full_name") or ""
    repo_short = full_name.split("/")[-1] if "/" in full_name else full_name
    repo_short = repo_short.lower()
    if repo_short:
        names.add(repo_short)
        for prefix in ("lovelace-", "ha-"):
            if repo_short.startswith(prefix):
                names.add(repo_short[len(prefix) :])

    return {n for n in names if n}


def _defined_elements(www_community_dir: Path, repo: dict) -> set[str]:
    """Liest die lokal installierte(n) JS-Datei(en) eines Plugin-Repos und
    extrahiert die per customElements.define() registrierten Namen – die
    exakte, verlässliche Quelle für den nutzbaren 'custom:<name>'-Typ."""
    full_name = repo.get("full_name") or ""
    repo_short = full_name.split("/")[-1] if "/" in full_name else full_name
    if not repo_short:
        return set()

    repo_dir = www_community_dir / repo_short
    if not repo_dir.is_dir():
        return set()

    js_files: list[Path] = []
    file_name = repo.get("file_name")
    if file_name:
        candidate = repo_dir / file_name
        if candidate.is_file():
            js_files.append(candidate)
    if not js_files:
        js_files = sorted(p for p in repo_dir.glob("*.js"))

    defined: set[str] = set()
    for js_file in js_files:
        try:
            content = js_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        defined |= {m.lower() for m in DEFINE_RE.findall(content)}
    return defined


def _collect_custom_types(node) -> set[str]:
    """Durchsucht rekursiv eine JSON-Struktur nach 'type: custom:xxx'."""
    found: set[str] = set()
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            type_val = current.get("type")
            if isinstance(type_val, str) and type_val.startswith(CUSTOM_PREFIX):
                found.add(type_val[len(CUSTOM_PREFIX) :].strip().lower())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _collect_registered_resources(storage_dir: Path) -> set[str]:
    """Liest registrierte Lovelace-Ressourcen-URLs (Dateiname, lowercase)."""
    data = _load(storage_dir / "lovelace_resources")
    items = data.get("data", {}).get("items", [])
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        stem = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if stem.endswith(".js"):
            stem = stem[: -len(".js")]
        if stem:
            names.add(stem.lower())
    return names


def run_scan_unused_cards(storage_dir_str: str, report_path_str: str) -> dict:
    """
    Vergleicht installierte HACS-Plugin-Repos mit tatsächlich in den
    Dashboards verwendeten Custom-Card-Typen.

    Wird im Executor ausgeführt (kein async).

    Args:
        storage_dir_str: Pfad zu .storage/ (z.B. /config/.storage)
        report_path_str: Pfad für den Vollbericht

    Returns:
        {"notification": str, "report": str, "used_count": int, "unused_count": int}
    """
    storage_dir = Path(storage_dir_str)
    report_path = Path(report_path_str)
    www_community_dir = storage_dir.parent / "www" / "community"

    plugins, plugin_status = _get_plugin_repos(storage_dir)
    registered = _collect_registered_resources(storage_dir)

    used_types: set[str] = set()
    scanned_files: list[str] = []
    # Storage-Modus: main dashboard = "lovelace", weitere = "lovelace.<url_path>",
    # zusätzlich lovelace_resources / lovelace_dashboards (schaden beim Scan nicht,
    # enthalten aber keine "custom:"-Treffer).
    for file in sorted(storage_dir.glob("lovelace*")):
        if not file.is_file():
            continue
        data = _load(file)
        if not data:
            continue
        used_types |= _collect_custom_types(data)
        scanned_files.append(file.name)

    lines_out: list[str] = []

    def w(text: str = "") -> None:
        lines_out.append(text)

    w(f"=== HACS Cleanup – Ungenutzte Karten-Scan – {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} ===")
    w()
    w(f"Installierte Plugin-Repos (Lovelace Custom Cards): {len(plugins)}  ({plugin_status})")
    w(f"Gescannte Storage-Dateien: {len(scanned_files)} ({', '.join(scanned_files) or '-'})")
    w(f"Gefundene custom:-Kartentypen in Dashboards: {len(used_types)}")
    w()
    w("HINWEIS: Primär wird die installierte JS-Datei unter www/community/<repo>/")
    w("nach customElements.define(...) durchsucht – das ist der exakte, tatsächlich")
    w("nutzbare Kartenname. Nur falls diese Datei nicht gefunden wird, greift eine")
    w("unsichere Namens-Heuristik als Fallback (im Bericht als solche markiert).")
    w("Nur YAML-Dashboards werden nicht gescannt (nur Storage-Modus/.storage/lovelace*).")
    w()

    used_repos: list[dict] = []
    unused_repos: list[dict] = []
    js_based = 0
    heuristic_based = 0

    for repo in plugins:
        defined = _defined_elements(www_community_dir, repo)
        heuristic = _heuristic_candidates(repo)
        # Immer beide Quellen kombinieren: die JS-Analyse kann ein Hilfselement
        # (z.B. "action-handler-<name>") statt des Haupt-Kartennamens finden,
        # wenn dieser über eine JS-Variable statt eines String-Literals an
        # customElements.define() übergeben wird (vom Regex nicht erfassbar).
        # Die Namens-Heuristik dient dann als zusätzliches Sicherheitsnetz und
        # erzeugt beim Abgleich keine falschen Treffer, da sie stets
        # repo-spezifisch bleibt.
        candidates = defined | heuristic
        if defined and (heuristic - defined):
            source = "JS-Analyse + Heuristik"
            js_based += 1
        elif defined:
            source = "JS-Analyse"
            js_based += 1
        else:
            source = "Namens-Heuristik (JS-Datei nicht gefunden)"
            heuristic_based += 1

        is_used = bool(candidates & used_types)
        is_registered = bool(candidates & registered)
        entry = {
            **repo,
            "candidates": sorted(candidates),
            "source": source,
            "used": is_used,
            "registered": is_registered,
        }
        (used_repos if is_used else unused_repos).append(entry)

    w(f"Erkennung: {js_based} über JS-Analyse (exakt), {heuristic_based} über Namens-Heuristik (Fallback)")
    w()

    w(f"--- Vermutlich GENUTZT ({len(used_repos)}) ---")
    if used_repos:
        for r in used_repos:
            w(f"  {r['name']}  [{r['full_name']}]  ({r['source']})")
            w(f"    Erkannt über: {', '.join(r['candidates']) or '-'}")
        w()
    else:
        w("  Keine")
        w()

    w(f"--- Vermutlich UNGENUTZT ({len(unused_repos)}) ---")
    if unused_repos:
        for r in unused_repos:
            reg_hint = (
                "als Ressource registriert, aber in keinem Dashboard gefunden"
                if r["registered"]
                else "auch keine Lovelace-Ressource dafür registriert"
            )
            w(f"  {r['name']}  [{r['full_name']}]  repo_id={r['id']}  ({r['source']})")
            w(f"    Gesuchte Namen: {', '.join(r['candidates']) or '-'}  ({reg_hint})")
        w()
    else:
        w("  Keine – alle installierten Karten scheinen genutzt zu werden.")
        w()

    w("--- Zusammenfassung ---")
    w(f"Genutzt   : {len(used_repos)}")
    w(f"Ungenutzt : {len(unused_repos)}")

    report_text = "\n".join(lines_out)

    try:
        report_path.write_text(report_text, encoding="utf-8")
    except OSError:
        pass

    notif_lines = [
        f"Plugin-Repos gesamt : {len(plugins)}",
        f"Vermutlich ungenutzt: {len(unused_repos)}",
    ]
    if unused_repos:
        notif_lines.append("")
        notif_lines.extend(f"• {r['name']}" for r in unused_repos[:10])
        if len(unused_repos) > 10:
            notif_lines.append(f"… und {len(unused_repos) - 10} weitere")
    notif_lines.append("")
    notif_lines.append(f"→ Details im Vollbericht: {report_path}")

    return {
        "notification": "\n".join(notif_lines),
        "report": report_text,
        "used_count": len(used_repos),
        "unused_count": len(unused_repos),
    }
