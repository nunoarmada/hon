import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyhon import Hon
from pyhon.exceptions import HonAuthenticationError

from .const import CONF_REFRESH_TOKEN, DOMAIN, MOBILE_ID, PLATFORMS

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
    try:
        hon = await Hon(
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            mobile_id=MOBILE_ID,
            session=session,
            test_data_path=Path(config_dir),
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN, ""),
        ).create()
    except HonAuthenticationError as err:
        raise ConfigEntryAuthFailed("hOn authentication failed") from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(f"Cannot connect to hOn: {err}") from err

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REFRESH_TOKEN: hon.api.auth.refresh_token}
    )

    async def async_update_data() -> dict[str, Any]:
        for appliance in hon.appliances:
            try:
                await appliance.update()
            except HonAuthenticationError as err:
                raise ConfigEntryAuthFailed("hOn authentication expired") from err
            except Exception as exc:
                _LOGGER.warning(
                    "Error refreshing %s: %s", appliance.mac_address, exc
                )
        return {}

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(minutes=5),
    )

    def _threadsafe_update(*args: Any, **kwargs: Any) -> None:
        hass.loop.call_soon_threadsafe(coordinator.async_set_updated_data, {})

    hon.subscribe_updates(_threadsafe_update)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = HonData(hon=hon, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HonConfigEntry) -> bool:
    refresh_token = entry.runtime_data.hon.api.auth.refresh_token
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REFRESH_TOKEN: refresh_token}
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hon = entry.runtime_data.hon
    mqtt = getattr(hon, "_mqtt_client", None)
    task = getattr(mqtt, "_watchdog_task", None)
    if task is not None and not task.done():
        task.cancel()
    try:
        await hon.close()
    except Exception as err:
        _LOGGER.debug("Error closing hOn connection: %s", err)
    return unload_ok
