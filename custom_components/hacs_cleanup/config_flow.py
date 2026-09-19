"""Config Flow für HACS Cleanup."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_EXCLUDED_REPOS, DOMAIN
from .integration_scanner import get_installed_integration_repos
from .usage_scanner import get_installed_plugin_repos


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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HacsCleanupOptionsFlow:
        """Options Flow für den Repo-Ausschluss bereitstellen."""
        return HacsCleanupOptionsFlow()


class HacsCleanupOptionsFlow(OptionsFlowWithReload):
    """Options Flow: installierte Repos auswählen, die von den
    Ungenutzt-Scans (Karten und Integrationen) ausgeschlossen werden sollen
    (z.B. Hilfs-Repos ohne eigene Karte wie card-mod)."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Einziger Schritt: Repo-Auswahl per Mehrfachauswahl (wie bei
        Entitäten, mit '+' hinzufügbar)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        storage_dir = self.hass.config.path(".storage")
        plugins = await self.hass.async_add_executor_job(
            get_installed_plugin_repos, storage_dir
        )
        integrations = await self.hass.async_add_executor_job(
            get_installed_integration_repos, storage_dir
        )

        options = [
            SelectOptionDict(
                value=p["id"], label=f"🧩 {p['name']} ({p['full_name']})"
            )
            for p in plugins
        ] + [
            SelectOptionDict(
                value=p["id"], label=f"⚙️ {p['name']} ({p['full_name']})"
            )
            for p in integrations
        ]

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_EXCLUDED_REPOS,
                    default=self.config_entry.options.get(
                        CONF_EXCLUDED_REPOS, []
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=False,
                    )
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
