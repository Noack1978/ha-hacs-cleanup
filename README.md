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

## Ungenutzte Karten finden (`hacs_cleanup.scan_unused_cards`)

Vergleicht alle installierten HACS-Plugin-Repos (Lovelace Custom Cards) mit den
Kartentypen, die tatsächlich in deinen Dashboards (Storage-Modus) verwendet werden,
und listet vermutlich ungenutzte Repos auf – als Grundlage, um sie in HACS zu deinstallieren.

**Erkennung:** Primär wird die lokal installierte JS-Datei unter
`/config/www/community/<repo>/` nach `customElements.define("name", ...)`
durchsucht – das ist der exakte Name, unter dem die Karte als `custom:name`
im Dashboard nutzbar ist, da jede gültige Lovelace-Karte sich zwingend so
registrieren muss. Nur falls diese Datei nicht gefunden/lesbar ist, greift
eine unsichere Namens-Heuristik als Fallback (im Bericht als solche
gekennzeichnet – dort dann manuell verifizieren). Gescannt werden nur
Storage-Modus-Dashboards (`.storage/lovelace*`) – reine YAML-Dashboards werden
aktuell nicht erfasst.

## Ungenutzte Integrationen finden (`hacs_cleanup.scan_unused_integrations`)

Vergleicht alle installierten HACS-Integration-Repos (`custom_components`) mit den
Integrationen, die tatsächlich in Home Assistant eingerichtet sind, und listet
vermutlich ungenutzte Repos auf – als Grundlage, um sie in HACS zu deinstallieren.

**Erkennung:** Zwei Signale werden geprüft:

1. **Config Entry** – existiert ein Eintrag in `.storage/core.config_entries`
   mit passender `domain`, gilt die Integration als genutzt.
2. **YAML-Referenz** – zusätzlich werden alle `*.yaml`/`*.yml`-Dateien im
   Konfigurationsordner (ohne `.storage`, `custom_components`, `www`,
   `themes`, `blueprints`, `__pycache__`) nach einem Top-Level-Schlüssel
   `<domain>:` oder einer Zeile `platform: <domain>` durchsucht – für
   Integrationen, die rein per YAML eingebunden werden (z.B. Sensoren ohne
   Config-Flow).

Die Domain eines Repos wird primär aus den HACS-Metadaten (`hacs.repositories`)
gelesen, ersatzweise über `custom_components/<name>/manifest.json` ermittelt
(inkl. gängiger Namensvarianten wie `ha-`/`homeassistant-`-Präfixe).

Kann die Domain für ein Repo nicht ermittelt werden, erscheint es im Bericht
im eigenen Abschnitt **"Domain nicht ermittelbar"** zur manuellen Prüfung –
es wird nicht automatisch als ungenutzt gewertet.

**Repos ausschließen:** Manche installierten Repos sind keine eigene Karte
bzw. keine eigenständig aktivierbare Integration (z.B. Hilfs-Repos wie
`card-mod`), werden dadurch nie als "genutzt" erkannt und würden fälschlich
als ungenutzt gelistet. Solche Repos lassen sich in der Integrationskonfiguration
ausschließen: Einstellungen → Geräte & Dienste → **HACS Cleanup** →
**Konfigurieren** → Repos per Mehrfachauswahl hinzufügen (wie bei einer
Entitäten-Auswahl). Karten sind dort mit 🧩, Integrationen mit ⚙️ markiert.
Ausgeschlossene Repos werden bei beiden Scans (Karten und Integrationen)
übersprungen und im jeweiligen Bericht im eigenen Abschnitt "Manuell
ausgeschlossen" aufgeführt.

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

Entwicklerwerkzeuge → Aktionen → `hacs_cleanup.scan`, `hacs_cleanup.scan_unused_cards` bzw. `hacs_cleanup.scan_unused_integrations` → Aktion ausführen

### Dashboard-Buttons

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

```yaml
show_name: true
show_icon: true
type: button
name: HACS Cleanup – Ungenutzte Karten
icon: mdi:cards-outline
tap_action:
  action: perform-action
  perform_action: hacs_cleanup.scan_unused_cards
  target: {}
show_state: false
```

```yaml
show_name: true
show_icon: true
type: button
name: HACS Cleanup – Ungenutzte Integrationen
icon: mdi:puzzle-outline
tap_action:
  action: perform-action
  perform_action: hacs_cleanup.scan_unused_integrations
  target: {}
show_state: false
```

### Ergebnis

- **HA-Benachrichtigung** mit Kurzübersicht erscheint direkt
- **Vollbericht** von `hacs_cleanup.scan` unter `/config/hacs_cleanup_report.txt`
- **Vollbericht** von `hacs_cleanup.scan_unused_cards` unter `/config/hacs_cleanup_unused_cards_report.txt`
- **Vollbericht** von `hacs_cleanup.scan_unused_integrations` unter `/config/hacs_cleanup_unused_integrations_report.txt`

## Hinweis

Das Skript scannt nur — es verändert keine Dateien. Gefundene Einträge müssen manuell entfernt werden (Anleitung steht im Vollbericht).

## Hinweise zur HA-Kompatibilität

### HA 2026.8+ – Device-Registry-Umstellung
Ab HA 2026.8 nutzt die Device-Registry intern `config_entry_id` statt `config_entries` (Liste).
Die Integration unterstützt beide Schemata automatisch per Fallback.

### HA 2026.9+ – Child Devices
Ab HA 2026.9 gibt es Child Devices mit `parent_device_id`. Diese werden beim Scan
explizit übersprungen, da sie über ihr Parent-Device verwaltet werden.

### HA 2026.9+ – Persistent Notification
Ab HA 2026.9 feuert eine Persistent Notification bei bestehender `notification_id`
das Event `update_type: updated` statt `added` (nur beim allerersten Erstellen `added`).
Falls du eine Automation auf das Notification-Event triggerst, ergänze dort `updated`.

