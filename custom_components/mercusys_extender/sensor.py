"""Status sensors for a Mercusys extender."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MercusysCoordinator


def _wireless_clients(status) -> list[dict[str, str | int | float]]:
    """Return the client details actually reported by the device."""
    clients = []
    for device in status.devices:
        connection = device.type
        if not device.active or not (
            connection.is_host_wifi()
            or connection.is_guest_wifi()
            or connection.is_iot()
        ):
            continue
        details = {
            "name": device.hostname or "",
            "ip": device.ipaddr,
            "mac": device.macaddr,
            "band": connection.get_band() or "",
            "network": connection.get_type() or "",
        }
        for field, name in (("rx_rate", "rx_rate_mbps"), ("tx_rate", "tx_rate_mbps")):
            value = getattr(device, field, None)
            if isinstance(value, (int, float)):
                details[name] = value
        clients.append(details)
    return sorted(clients, key=lambda item: (item["name"].lower(), item["mac"]))


def _band_count(status, band: str) -> int:
    """Count active wireless clients on a reported radio band."""
    return sum(
        1
        for device in status.devices
        if device.active
        and (device.type.is_host_wifi() or device.type.is_guest_wifi() or device.type.is_iot())
        and device.type.get_band() == band
    )


SENSORS: dict[str, Callable] = {
    "wireless_clients": lambda status: (
        status.wifi_clients_total
        + status.guest_clients_total
        + (status.iot_clients_total or 0)
    ),
    "main_wireless_clients": lambda status: status.wifi_clients_total,
    "guest_wireless_clients": lambda status: status.guest_clients_total,
    "wired_clients": lambda status: status.wired_total,
    "wireless_clients_2g": lambda status: _band_count(status, "2G"),
    "wireless_clients_5g": lambda status: _band_count(status, "5G"),
    "wireless_clients_6g": lambda status: _band_count(status, "6G"),
    "wireless_clients_mlo": lambda status: _band_count(status, "MLO"),
    "wan_connection_uptime": lambda status: status.wan_ipv4_uptime,
    "cpu_usage": lambda status: (
        round(status.cpu_usage * 100, 1) if status.cpu_usage is not None else None
    ),
    "memory_usage": lambda status: (
        round(status.mem_usage * 100, 1) if status.mem_usage is not None else None
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add status sensors for this extender."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [MercusysStatusSensor(coordinator, entry, key) for key in SENSORS]
        + [
            MercusysLastStatusSensor(coordinator, entry),
            MercusysLastRebootSensor(coordinator, entry),
        ]
    )


class MercusysBaseSensor(CoordinatorEntity[MercusysCoordinator], SensorEntity):
    """Base class sharing the extender device registry entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MercusysCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Mercusys",
            configuration_url=entry.data[CONF_HOST],
        )


class MercusysStatusSensor(MercusysBaseSensor):
    """A value returned by the extender's status endpoint."""

    def __init__(self, coordinator: MercusysCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator, entry, key)
        self._key = key
        if key == "wan_connection_uptime":
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        elif key in ("cpu_usage", "memory_usage"):
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:cpu-64-bit" if key == "cpu_usage" else "mdi:memory"
        else:
            self._attr_icon = "mdi:lan" if key == "wired_clients" else "mdi:account-multiple"
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the latest reported value."""
        if self.coordinator.data is None:
            return None
        return SENSORS[self._key](self.coordinator.data)

    @property
    def extra_state_attributes(self):
        """Show client details on the total wireless client sensor."""
        if self._key != "wireless_clients" or self.coordinator.data is None:
            return None
        return {"clients": _wireless_clients(self.coordinator.data)}


class MercusysLastRebootSensor(MercusysBaseSensor):
    """Time of the last reboot command sent through this integration."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: MercusysCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_reboot_requested")

    @property
    def available(self) -> bool:
        """The saved command time remains available when polling fails."""
        return True

    @property
    def native_value(self):
        """Return the last locally recorded reboot command time."""
        return self.coordinator.last_reboot_requested


class MercusysLastStatusSensor(MercusysBaseSensor):
    """Time of the most recent successful status poll."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: MercusysCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_status_update")

    @property
    def available(self) -> bool:
        """Keep the last successful timestamp visible during an outage."""
        return True

    @property
    def native_value(self):
        """Return the time when the last status request completed."""
        return self.coordinator.last_status_update
