"""Local API used by Mercusys ME25BE firmware (CE RED generation)."""

from __future__ import annotations

from base64 import b64decode, b64encode
from hashlib import sha256
from hmac import new as hmac_new
import json
from secrets import choice
from urllib.parse import urlencode

from Crypto.Cipher import AES, PKCS1_OAEP, PKCS1_v1_5
from Crypto.PublicKey.RSA import construct
from Crypto.Util.Padding import pad, unpad
import requests
from tplinkrouterc6u.common.dataclass import Status


class ME25BEAuthenticationError(Exception):
    """Login failed or its outcome is unknown; do not retry automatically."""


class ME25BEClient:
    """Short lived authenticated session for the ME25BE web API."""

    def __init__(self, host: str, password: str, username: str = "admin", verify_ssl: bool = False, timeout: int = 10) -> None:
        self.host = host.rstrip("/")
        self.password = password
        # The local UI has no username field. Firmware uses admin internally.
        self.username = "admin"
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Origin": self.host,
                "Referer": f"{self.host}/",
                "Cache-Control": "no-cache",
            }
        )
        self.key = "".join(choice("0123456789") for _ in range(16))
        self.iv = "".join(choice("0123456789") for _ in range(16))
        self.token = ""
        self.sequence = 0
        self.sign_key = None
        self.identified = False

    def _url(self, path: str) -> str:
        return f"{self.host}/cgi-bin/luci/;stok={self.token}/{path}"

    def _plain_read(self, form: str) -> dict:
        response = self.session.post(self._url(f"login?form={form}"), data={"operation": "read"}, timeout=self.timeout, verify=self.verify_ssl)
        response.raise_for_status()
        body = response.json()
        if not body.get("success") or not isinstance(body.get("data"), dict):
            raise ValueError(f"Could not read ME25BE {form} keys")
        return body["data"]

    @staticmethod
    def _rsa_key(parts: list[str]):
        return construct((int(parts[0], 16), int(parts[1], 16)))

    def _encrypt(self, fields: dict) -> str:
        raw = urlencode(fields).encode()
        cipher = AES.new(self.key.encode(), AES.MODE_CBC, self.iv.encode())
        return b64encode(cipher.encrypt(pad(raw, 16))).decode()

    def _decrypt(self, encoded: str) -> dict:
        cipher = AES.new(self.key.encode(), AES.MODE_CBC, self.iv.encode())
        return json.loads(unpad(cipher.decrypt(b64decode(encoded)), 16).decode())

    def _post(self, path: str, fields: dict, *, login: bool = False) -> dict:
        encrypted = self._encrypt(fields)
        hash_value = sha256((self.username + self.password).encode()).hexdigest() if login else sha256(encrypted.encode()).hexdigest()
        raw_sign = f"h={hash_value}&s={self.sequence + len(encrypted)}"
        aes_key = f"k={self.key}&i={self.iv}"
        if login:
            signed = f"{aes_key}&{raw_sign}"
            cipher = PKCS1_OAEP.new(self.sign_key)
            sign = "".join(cipher.encrypt(signed[i:i + 53].encode()).hex() for i in range(0, len(signed), 53))
        else:
            sign = "".join(hmac_new(aes_key.encode(), raw_sign[i:i + 53].encode(), sha256).hexdigest() for i in range(0, len(raw_sign), 53))
        response = self.session.post(self._url(path), data={"sign": sign, "data": encrypted}, timeout=self.timeout, verify=self.verify_ssl)
        response.raise_for_status()
        body = response.json()
        result = self._decrypt(body["data"]) if isinstance(body.get("data"), str) else body
        if not result.get("success"):
            raise ValueError(f"ME25BE request failed: {result.get('errorCode', result.get('error', 'unknown'))}")
        return result.get("data") or {}

    def authorize(self) -> None:
        try:
            keys = self._plain_read("keys")
            self.identified = "mode" in keys and "username" in keys
            auth = self._plain_read("auth")
        except requests.HTTPError as err:
            if err.response is not None and err.response.status_code == 403:
                raise ME25BEAuthenticationError("ME25BE access denied") from err
            raise
        password_key = self._rsa_key(keys["password"])
        self.sign_key = self._rsa_key(auth["key"])
        self.sequence = int(auth["seq"])
        encrypted_password = PKCS1_v1_5.new(password_key).encrypt(self.password.encode()).hex()
        try:
            result = self._post(
                "login?form=login",
                {"operation": "login", "password": encrypted_password},
                login=True,
            )
            self.token = result["stok"]
        except (requests.RequestException, ValueError, KeyError) as err:
            raise ME25BEAuthenticationError("ME25BE login failed or response was lost") from err

    def get_status(self) -> Status:
        # The network map reads this endpoint for the connected client list.
        clients = self._post("admin/status?form=device", {"operation": "read"})
        if isinstance(clients, dict):
            clients = next((value for value in clients.values() if isinstance(value, list)), [])
        if not isinstance(clients, list):
            raise ValueError("Unexpected ME25BE client response")
        status = Status()
        for item in clients:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type", "")).upper()
            if kind == "WIRED":
                status.wired_total += 1
            elif kind in ("2.4GHZ", "5GHZ", "5G2HZ", "6GHZ", "MLO"):
                status.wifi_clients_total += 1
                status.devices.append(_client_device(item, kind))
        try:
            guests = self._post("admin/status?form=guest", {"operation": "read"})
        except (requests.RequestException, ValueError, KeyError):
            # Guest client reporting can be disabled by firmware settings.
            guests = []
        if isinstance(guests, dict):
            guests = next((value for value in guests.values() if isinstance(value, list)), [])
        if isinstance(guests, list):
            for item in guests:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("type", "")).upper()
                if kind in ("2.4GHZ", "5GHZ", "5G2HZ", "6GHZ", "MLO"):
                    status.guest_clients_total += 1
                    status.devices.append(_client_device(item, kind, guest=True))
        status.clients_total = status.wired_total + status.wifi_clients_total + status.guest_clients_total
        try:
            performance = self._post("admin/status?form=perf", {"operation": "read"})
        except (requests.RequestException, ValueError, KeyError):
            performance = None
        if isinstance(performance, dict):
            for field, attribute in (("cpu_usage", "cpu_usage"), ("mem_usage", "mem_usage")):
                try:
                    value = float(performance[field])
                except (KeyError, TypeError, ValueError):
                    continue
                if 0 <= value <= 1:
                    setattr(status, attribute, value)
        return status

    def reboot(self) -> None:
        self._post("admin/system?form=reboot", {"operation": "reboot"})

    def logout(self) -> None:
        try:
            if self.token:
                # The web UI sends an empty encrypted request for logout.
                self._post("admin/system?form=logout", {})
        finally:
            self.session.close()


def _client_device(item: dict, kind: str, guest: bool = False):
    """Adapt firmware client data to the existing sensor display."""
    from types import SimpleNamespace
    from tplinkrouterc6u.common.package_enum import Connection

    types = {
        "2.4GHZ": Connection.HOST_2G,
        "5GHZ": Connection.HOST_5G,
        "5G2HZ": Connection.HOST_5G_2,
        "6GHZ": Connection.HOST_6G,
        "MLO": Connection.HOST_MLO,
    }
    guest_types = {
        "2.4GHZ": Connection.GUEST_2G,
        "5GHZ": Connection.GUEST_5G,
        "5G2HZ": Connection.GUEST_5G_2,
        "6GHZ": Connection.GUEST_6G,
        "MLO": Connection.GUEST_5G,
    }
    return SimpleNamespace(
        type=(guest_types if guest else types)[kind], active=True,
        hostname=str(item.get("name") or ""),
        ipaddr=str(item.get("ipaddr") or item.get("ip") or ""),
        macaddr=str(item.get("mac") or ""),
        rx_rate=item.get("rxrate"),
        tx_rate=item.get("txrate"),
    )
