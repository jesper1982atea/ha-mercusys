"""Periodic status polling and locally recorded reboot requests."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from requests import HTTPError

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.logbook import async_log_entry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import fetch_status
from .const import CONF_CLIENT_CLASS, CONF_VERIFY_SSL, DOMAIN
from .me25be import ME25BEAuthenticationError

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(minutes=5)


class MercusysCoordinator(DataUpdateCoordinator):
    """Keep one extender's client status current."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.last_reboot_requested: datetime | None = None
        self.last_status_update: datetime | None = None
        self._online_state: bool | None = None
        self._auth_failed_latched = False
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")

    def _log_activity(self, message_sv: str, message_en: str, entity_key: str) -> None:
        """Record a device-linked event without exposing credentials or client details."""
        platform = "button" if entity_key == "reboot" else "sensor"
        entity_id = er.async_get(self.hass).async_get_entity_id(
            platform, DOMAIN, f"{self.entry.entry_id}_{entity_key}"
        )
        if entity_id is None:
            return
        message = message_sv if self.hass.config.language.startswith("sv") else message_en
        async_log_entry(self.hass, self.entry.title, message, DOMAIN, entity_id)

    async def async_load(self) -> None:
        """Restore the most recent command timestamp."""
        saved = await self._store.async_load()
        if saved and (value := saved.get("last_reboot_requested")):
            try:
                self.last_reboot_requested = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring invalid saved reboot timestamp for %s", self.entry.title)

    async def async_record_reboot(self) -> None:
        """Record a successfully submitted reboot command."""
        self.last_reboot_requested = dt_util.utcnow()
        self.async_update_listeners()
        self._log_activity("Omstartskommando skickades", "Reboot command sent", "reboot")
        try:
            await self._store.async_save(
                {"last_reboot_requested": self.last_reboot_requested.isoformat()}
            )
        except Exception:
            _LOGGER.exception("Could not save last reboot request for %s", self.entry.title)

    async def _async_update_data(self):
        """Poll the extender without blocking the event loop."""
        data = self.entry.data
        if self._auth_failed_latched:
            raise UpdateFailed(
                "ME25BE login was unsuccessful; reload the integration after resolving access"
            )
        try:
            status = await self.hass.async_add_executor_job(
                fetch_status,
                data[CONF_HOST],
                data[CONF_PASSWORD],
                data[CONF_USERNAME],
                data[CONF_VERIFY_SSL],
                data[CONF_CLIENT_CLASS],
            )
        except Exception as err:
            if isinstance(err, ME25BEAuthenticationError) or (
                data[CONF_CLIENT_CLASS] == "ME25BEClient"
                and isinstance(err, HTTPError)
                and err.response is not None
                and err.response.status_code == 403
            ):
                self._auth_failed_latched = True
                _LOGGER.warning(
                    "ME25BE login failed at %s; automatic login attempts paused",
                    data[CONF_HOST],
                )
                self._log_activity(
                    "Inloggning misslyckades; automatiska försök pausade",
                    "Login failed; automatic attempts paused",
                    "last_status_update",
                )
            if self._online_state is True:
                self._log_activity(
                    "Kontakten med extendern bröts",
                    "Connection to extender lost",
                    "last_status_update",
                )
            self._online_state = False
            raise UpdateFailed(f"Could not read status from {data[CONF_HOST]}") from err
        if self._online_state is False:
            self._log_activity(
                "Kontakten med extendern återställdes",
                "Connection to extender restored",
                "last_status_update",
            )
        self._online_state = True
        self.last_status_update = dt_util.utcnow()
        return status
