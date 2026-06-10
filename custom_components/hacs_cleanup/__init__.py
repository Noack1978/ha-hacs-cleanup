"""HACS Cleanup Integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, NOTIFICATION_ID, REPORT_FILENAME, SERVICE_SCAN
from .scanner import run_scan

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Integration einrichten und Service registrieren."""

    async def handle_scan(call: ServiceCall) -> None:
        """Service-Handler: Scan ausführen und Ergebnis als Notification anzeigen."""
        storage_dir = hass.config.path(".storage")
        report_path = hass.config.path(REPORT_FILENAME)

        _LOGGER.debug("HACS Cleanup Scan gestartet")

        result = await hass.async_add_executor_job(
            run_scan, storage_dir, report_path
        )

        hass.components.persistent_notification.async_create(
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

    hass.services.async_register(DOMAIN, SERVICE_SCAN, handle_scan)
    _LOGGER.debug("HACS Cleanup Service '%s.%s' registriert", DOMAIN, SERVICE_SCAN)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Integration entladen."""
    hass.services.async_remove(DOMAIN, SERVICE_SCAN)
    return True
