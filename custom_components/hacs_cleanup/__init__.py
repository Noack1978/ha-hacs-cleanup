"""HACS Cleanup Integration."""

from __future__ import annotations

import logging

from homeassistant.components.persistent_notification import (
    async_create as pn_create,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_EXCLUDED_REPOS,
    DOMAIN,
    NOTIFICATION_ID,
    NOTIFICATION_ID_UNUSED_CARDS,
    REPORT_FILENAME,
    REPORT_FILENAME_UNUSED_CARDS,
    SERVICE_SCAN,
    SERVICE_SCAN_UNUSED_CARDS,
)
from .scanner import run_scan
from .usage_scanner import run_scan_unused_cards

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Integration einrichten und Services registrieren."""

    async def handle_scan(call: ServiceCall) -> None:
        storage_dir = hass.config.path(".storage")
        report_path = hass.config.path(REPORT_FILENAME)

        _LOGGER.debug("HACS Cleanup Scan gestartet")

        try:
            result = await hass.async_add_executor_job(
                run_scan, storage_dir, report_path
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("HACS Cleanup Scan fehlgeschlagen")
            pn_create(
                hass,
                f"Scan fehlgeschlagen: {err}\n\nDetails im HA-Log (Einstellungen → System → Logs).",
                title="⚠️ HACS Cleanup – Fehler",
                notification_id=NOTIFICATION_ID,
            )
            return

        pn_create(
            hass,
            result["notification"],
            title="🔍 HACS Cleanup – Scan-Ergebnis",
            notification_id=NOTIFICATION_ID,
        )

        if result["findings"] > 0:
            _LOGGER.warning(
                "HACS Cleanup: %d verwaiste Einträge gefunden. Vollbericht: %s",
                result["findings"],
                report_path,
            )
        else:
            _LOGGER.info("HACS Cleanup: Alles sauber.")

    async def handle_scan_unused_cards(call: ServiceCall) -> None:
        storage_dir = hass.config.path(".storage")
        report_path = hass.config.path(REPORT_FILENAME_UNUSED_CARDS)

        excluded_ids = entry.options.get(CONF_EXCLUDED_REPOS, [])

        _LOGGER.debug(
            "HACS Cleanup Ungenutzte-Karten-Scan gestartet (%d Repos ausgeschlossen)",
            len(excluded_ids),
        )

        try:
            result = await hass.async_add_executor_job(
                run_scan_unused_cards, storage_dir, report_path, excluded_ids
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("HACS Cleanup Ungenutzte-Karten-Scan fehlgeschlagen")
            pn_create(
                hass,
                f"Scan fehlgeschlagen: {err}\n\nDetails im HA-Log (Einstellungen → System → Logs).",
                title="⚠️ HACS Cleanup – Fehler",
                notification_id=NOTIFICATION_ID_UNUSED_CARDS,
            )
            return

        pn_create(
            hass,
            result["notification"],
            title="🧹 HACS Cleanup – Ungenutzte Karten",
            notification_id=NOTIFICATION_ID_UNUSED_CARDS,
        )

        if result["unused_count"] > 0:
            _LOGGER.warning(
                "HACS Cleanup: %d vermutlich ungenutzte Karten-Repos gefunden. Vollbericht: %s",
                result["unused_count"],
                report_path,
            )
        else:
            _LOGGER.info("HACS Cleanup: Alle installierten Karten scheinen genutzt zu werden.")

    hass.services.async_register(DOMAIN, SERVICE_SCAN, handle_scan)
    hass.services.async_register(
        DOMAIN, SERVICE_SCAN_UNUSED_CARDS, handle_scan_unused_cards
    )
    _LOGGER.debug(
        "HACS Cleanup Services '%s.%s' und '%s.%s' registriert",
        DOMAIN, SERVICE_SCAN, DOMAIN, SERVICE_SCAN_UNUSED_CARDS,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Integration entladen."""
    hass.services.async_remove(DOMAIN, SERVICE_SCAN)
    hass.services.async_remove(DOMAIN, SERVICE_SCAN_UNUSED_CARDS)
    return True
