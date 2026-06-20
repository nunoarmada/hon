from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from pyhon.appliance import HonAppliance

from .const import DOMAIN
from .typedefs import HonEntityDescription


class HonEntity(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]]):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: HonAppliance,
        description: HonEntityDescription | None = None,
    ) -> None:
        self.coordinator = entry.runtime_data.coordinator
        super().__init__(self.coordinator)
        self._hon = entry.runtime_data.hon
        self._device: HonAppliance = device

        if description is not None:
            self.entity_description = description
            self._attr_unique_id = f"{self._device.unique_id}{description.key}"
        else:
            self._attr_unique_id = self._device.unique_id
        self._handle_coordinator_update(update=False)

    @property
    def _device_connected(self) -> bool:
        """Return the real connection state of the appliance.

        pyhOn's ``HonAppliance.connection`` is initialised once from empty
        attributes and never updated, so it stays ``True`` even when the
        appliance is physically offline. Derive the state from the live
        ``lastConnEvent.category`` attribute instead (#329). Absence of the
        attribute is treated as connected to preserve previous behaviour.
        """
        return self._device.get("attributes.lastConnEvent.category") != "DISCONNECTED"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.unique_id)},
            manufacturer=self._device.get("brand", "").capitalize(),
            name=self._device.nick_name,
            model=self._device.model_name,
            sw_version=self._device.get("fwVersion", ""),
            hw_version=f"{self._device.appliance_type}{self._device.model_id}",
            serial_number=self._device.get("serialNumber", ""),
        )

    @callback
    def _handle_coordinator_update(self, update: bool = True) -> None:
        if update:
            self.async_write_ha_state()
