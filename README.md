# HACS Cleanup

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Scannt Home Assistant nach verwaisten Einträgen, die nach dem Entfernen von HACS-Repositories zurückbleiben.

## Was wird erkannt?

| Abschnitt | Was wird gesucht |
|-----------|-----------------|
| 1 | Entitäten deren `config_entry_id` nicht mehr existiert |
| 2 | Geräte deren `config_entry_id` nicht mehr existiert |
| 3 | HACS-Geräte deren Repo nicht mehr in `hacs.repositories` steht |
| 4 | HACS-Entitäten deren Repo nicht mehr in `hacs.repositories` steht |

Für jeden Fund wird die genaue **Datei** und **Zeilennummer** im Vollbericht angegeben.

## Installation

### Via HACS (empfohlen)

1. HACS öffnen → Integrationen → drei Punkte → **Custom Repositories**
2. URL `https://github.com/Noack1978/ha-hacs-cleanup` hinzufügen, Kategorie: **Integration**
3. **HACS Cleanup** installieren
4. HA neu starten
5. Einstellungen → Geräte & Dienste → **+ Integration hinzufügen** → **HACS Cleanup**

### Manuell

`custom_components/hacs_cleanup/` in den HA-Konfigurationsordner kopieren und HA neu starten.

## Verwendung

### Service aufrufen

Entwicklerwerkzeuge → Aktionen → `hacs_cleanup.scan` → Aktion ausführen

### Dashboard-Button

```yaml
show_name: true
show_icon: true
type: button
name: HACS Cleanup – Scan starten
icon: mdi:magnify-scan
tap_action:
  action: perform-action
  perform_action: hacs_cleanup.scan
  target: {}
show_state: false
```

### Ergebnis

- **HA-Benachrichtigung** mit Kurzübersicht erscheint direkt
- **Vollbericht** unter `/config/hacs_cleanup_report.txt` mit Datei und Zeilennummer je Fund

## Hinweis

Das Skript scannt nur — es verändert keine Dateien. Gefundene Einträge müssen manuell entfernt werden (Anleitung steht im Vollbericht).
