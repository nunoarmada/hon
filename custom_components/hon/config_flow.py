import logging
from typing import Any

import aiohttp
import voluptuous as vol  # type: ignore[import-untyped]
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import aiohttp_client
from pyhon.connection.api import HonAPI
from pyhon.exceptions import HonAuthenticationError

from .const import CONF_REFRESH_TOKEN, DOMAIN, MOBILE_ID

_LOGGER = logging.getLogger(__name__)


class HonFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None

    async def _validate_login(
        self, hass: HomeAssistant, email: str, password: str
    ) -> tuple[str | None, str | None]:
        session = aiohttp_client.async_get_clientsession(hass)
        # Validate credentials with an auth-only API client. The full
        # ``Hon().create()`` also loads appliances and starts the MQTT client,
        # which performs blocking ``importlib.metadata`` reads (awsiotsdk) in
        # the event loop. None of that is needed just to check the login.
        api = HonAPI(
            email=email,
            password=password,
            mobile_id=MOBILE_ID,
            session=session,
        )
        try:
            await api.create()
            return api.auth.refresh_token, None
        except HonAuthenticationError:
            return None, "invalid_auth"
        except aiohttp.ClientError:
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during hOn login")
            return None, "unknown"
        finally:
            # Only closes handler resources; the shared HA session is kept open.
            await api.close()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()

            refresh_token, error = await self._validate_login(
                self.hass, self._email, self._password
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=self._email,
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_REFRESH_TOKEN: refresh_token or "",
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=(self._email or "")): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            refresh_token, error = await self._validate_login(
                self.hass,
                self._reauth_entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_TOKEN: refresh_token or "",
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={
                "email": self._reauth_entry.data[CONF_EMAIL],
            },
            errors=errors,
        )

    async def async_step_import(self, user_input: dict[str, str]) -> ConfigFlowResult:
        return await self.async_step_user(user_input)
