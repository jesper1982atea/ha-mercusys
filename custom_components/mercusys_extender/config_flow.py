"""UI setup for a Mercusys range extender."""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .client import discover_client
from .const import CONF_CLIENT_CLASS, CONF_VERIFY_SSL, DOMAIN
from .me25be import ME25BEAuthenticationError

_LOGGER = logging.getLogger(__name__)


def _normalize_host(value: str) -> str:
    """Accept a LAN IP, optionally with an HTTP(S) scheme and port."""
    value = value.strip()
    parsed = urlsplit(value if "://" in value else f"http://{value}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("invalid host")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("invalid host")
    try:
        ipaddress.ip_address(parsed.hostname)
        port = parsed.port
    except (ValueError, TypeError) as err:
        raise ValueError("invalid host") from err
    authority = parsed.hostname
    if ":" in authority:
        authority = f"[{authority}]"
    if port is not None:
        authority = f"{authority}:{port}"
    return f"{parsed.scheme}://{authority}"


class MercusysExtenderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one extender per IP address."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Validate access and save the working protocol."""
        errors = {}
        if user_input is not None:
            try:
                host = _normalize_host(user_input[CONF_HOST])
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                # A bare IP often opens HTTPS in a browser, even when HTTP was
                # typed. Probe both schemes and retain the one that works.
                hosts = [host]
                if "://" not in user_input[CONF_HOST]:
                    hosts.append(host.replace("http://", "https://", 1))
                client_class = None
                for candidate in hosts:
                    try:
                        client_class = await self.hass.async_add_executor_job(
                            discover_client,
                            candidate,
                            user_input[CONF_PASSWORD],
                            "admin",
                            user_input[CONF_VERIFY_SSL],
                        )
                    except ME25BEAuthenticationError:
                        # A second HTTPS attempt would count as another failed
                        # login on ME25BE and can lock its local account.
                        _LOGGER.warning(
                            "ME25BE login failed at %s; not trying another protocol",
                            candidate,
                        )
                        break
                    except Exception as err:
                        _LOGGER.warning(
                            "Could not validate extender at %s (%s)",
                            candidate,
                            type(err).__name__,
                        )
                    else:
                        host = candidate
                        break

                if client_class is None:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(host)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Mercusys {urlsplit(host).hostname}",
                        data={
                            CONF_HOST: host,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_USERNAME: "admin",
                            CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                            CONF_CLIENT_CLASS: client_class,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "192.168.1.10")): str,
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
                ),
                vol.Required(CONF_VERIFY_SSL, default=(user_input or {}).get(CONF_VERIFY_SSL, False)): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
