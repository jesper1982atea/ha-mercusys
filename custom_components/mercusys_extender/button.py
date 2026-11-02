"""Reboot button for a Mercusys extender."""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import reboot_client
from .const import CONF_CLIENT_CLASS, CONF_VERIFY_SSL, DOMAIN
from .coordinator import MercusysCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add one reboot button for the configured extender."""
    async_add_entities([MercusysRebootButton(entry, hass.data[DOMAIN][entry.entry_id])])


class MercusysRebootButton(ButtonEntity):
    """Send a reboot request when pressed or called from an automation."""

    _attr_has_entity_name = True
    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, coordinator: MercusysCoordinator) -> None:
        self._entry = entry
        self._coordinator = coordinator
        host = entry.data[CONF_HOST]
        self._attr_unique_id = f"{entry.entry_id}_reboot"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Mercusys",
            configuration_url=host,
        )

    async def async_press(self) -> None:
        """Request a reboot without blocking Home Assistant's event loop."""
        data = self._entry.data
        try:
            await self.hass.async_add_executor_job(
                reboot_client,
                data[CONF_HOST],
                data[CONF_PASSWORD],
                data[CONF_USERNAME],
                data[CONF_VERIFY_SSL],
                data[CONF_CLIENT_CLASS],
            )
        except Exception as err:
            raise HomeAssistantError("Could not reboot the Mercusys extender") from err
        await self._coordinator.async_record_reboot()
