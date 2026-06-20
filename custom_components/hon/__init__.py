import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyhon import Hon

from .const import DOMAIN, PLATFORMS, MOBILE_ID, CONF_REFRESH_TOKEN

_LOGGER = logging.getLogger(__name__)


@dataclass
class HonData:
    hon: Hon
    coordinator: DataUpdateCoordinator[dict[str, Any]]


type HonConfigEntry = ConfigEntry[HonData]


async def async_setup_entry(hass: HomeAssistant, entry: HonConfigEntry) -> bool:
    session = aiohttp_client.async_get_clientsession(hass)
    if (config_dir := hass.config.config_dir) is None:
        raise ValueError("Missing Config Dir")
    hon = await Hon(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        mobile_id=MOBILE_ID,
        session=session,
        test_data_path=Path(config_dir),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN, ""),
    ).create()

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REFRESH_TOKEN: hon.api.auth.refresh_token}
    )

    async def async_update_data() -> dict[str, Any]:
        try:
            appliances_data = await hon.api.load_appliances()
            if not isinstance(appliances_data, list):
                _LOGGER.warning(
                    "Unexpected appliances_data type: %s", type(appliances_data)
                )
                return {}
            for new_appliance_data in appliances_data:
                if not isinstance(new_appliance_data, dict):
                    continue
                mac = new_appliance_data.get("macAddress")
                if not mac:
                    continue
                for appliance in hon.appliances:
                    if appliance.mac_address == mac:
                        appliance._data = new_appliance_data
                        break
        except Exception as exc:
            _LOGGER.warning("Error during Hon API poll: %s", exc)
        return {}

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=60),
    )

    def _threadsafe_update(*args: Any, **kwargs: Any) -> None:
        hass.loop.call_soon_threadsafe(
            coordinator.async_set_updated_data, *args, **kwargs
        )

    hon.subscribe_updates(_threadsafe_update)

    entry.runtime_data = HonData(hon=hon, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HonConfigEntry) -> bool:
    refresh_token = entry.runtime_data.hon.api.auth.refresh_token
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REFRESH_TOKEN: refresh_token}
    )
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
