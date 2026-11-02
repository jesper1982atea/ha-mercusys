"""Blocking access to the extender's local web API."""

import logging
from urllib.parse import urlsplit

from requests import HTTPError

from tplinkrouterc6u.provider import TplinkRouterProvider

from .me25be import ME25BEAuthenticationError, ME25BEClient

_LOGGER = logging.getLogger(__name__)


def _create_client(
    host: str, password: str, username: str, verify_ssl: bool, client_class: str
):
    client_type = (
        ME25BEClient
        if client_class == "ME25BEClient"
        else TplinkRouterProvider.get_clients()[client_class]
    )
    return client_type(host, password, username, verify_ssl=verify_ssl, timeout=10)


def fetch_status(
    host: str, password: str, username: str, verify_ssl: bool, client_class: str
):
    """Read the local status using one short-lived authenticated session."""
    client = _create_client(host, password, username, verify_ssl, client_class)
    try:
        client.authorize()
        return client.get_status()
    finally:
        try:
            client.logout()
        except Exception:
            pass


def discover_client(host: str, password: str, username: str, verify_ssl: bool) -> str:
    """Find a working protocol and verify credentials without changing the device."""
    # ME25BE uses SHA-256, RSA-OAEP and HMAC signatures. The upstream
    # provider's legacy extender clients cannot authenticate to it.
    modern = ME25BEClient(host, password, verify_ssl=verify_ssl, timeout=5)
    try:
        modern.authorize()
    except Exception as err:
        _LOGGER.warning("ME25BE login failed at %s: %s", host, _safe_error(err))
        modern.session.close()
        if modern.identified or isinstance(err, ME25BEAuthenticationError) or (
            isinstance(err, HTTPError)
            and err.response is not None
            and err.response.status_code == 403
        ):
            # A recognized ME25BE must not be retried by every legacy client.
            raise
    else:
        try:
            modern.get_status()
        except Exception as err:
            _LOGGER.warning("ME25BE status failed at %s: %s", host, _safe_error(err))
            try:
                modern.logout()
            except Exception:
                pass
            # Authentication succeeded. A status failure must not cause a
            # second login attempt through the legacy protocol probes.
            if (
                isinstance(err, HTTPError)
                and err.response is not None
                and err.response.status_code == 403
            ):
                raise ME25BEAuthenticationError("ME25BE access denied") from err
            raise
        else:
            try:
                modern.logout()
            except Exception:
                pass
            return "ME25BEClient"

    client = TplinkRouterProvider.get_client(
        host, password, username, verify_ssl=verify_ssl, timeout=5
    )
    client.authorize()
    try:
        return type(client).__name__
    finally:
        try:
            client.logout()
        except Exception:
            # Some firmware closes the session before answering logout.
            pass


def _safe_error(err: Exception) -> str:
    """Describe failures without logging credentials or session tokens."""
    if isinstance(err, HTTPError) and err.response is not None:
        response = err.response
        query = urlsplit(response.url).query
        form = query.removeprefix("form=").split("&", 1)[0]
        return f"HTTP {response.status_code} at form={form or 'unknown'}"
    if isinstance(err, ValueError) and type(err) is ValueError:
        return str(err)
    if isinstance(err, KeyError):
        return f"missing response field {err}"
    return type(err).__name__


def reboot_client(
    host: str, password: str, username: str, verify_ssl: bool, client_class: str
) -> None:
    """Log in, request a reboot, and close the session if still possible."""
    client = _create_client(host, password, username, verify_ssl, client_class)
    try:
        client.authorize()
        client.reboot()
    finally:
        try:
            client.logout()
        except Exception:
            # A successful reboot normally ends the HTTP session immediately.
            pass
