"""Config Flow für HACS Cleanup."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class HacsCleanupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow – keine Eingabe nötig, direkt einrichten."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Einziger Schritt: Integration sofort anlegen."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="HACS Cleanup", data={})
