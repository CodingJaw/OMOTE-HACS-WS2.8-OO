"""Host validation and serializable setup form for HA 2024.9.1.

Home Assistant's config-flow renderer must serialize the form schema. Do not
put custom function validators directly into vol.Schema fields: older
voluptuous_serialize versions reject them. Validate the host on submission.
"""
from __future__ import annotations

import ipaddress

import voluptuous as vol


DEFAULT_PORT = 80


def normalize_host(value: str) -> str:
    """Normalize and validate a DNS hostname or IPv4 address.

    URL schemes, credentials and paths are not accepted; only a network host.
    """
    if not isinstance(value, str):
        raise vol.Invalid("Host must be a string")
    host = value.strip().lower()
    if not host or len(host) > 253 or any(c in host for c in "/:@?#% \\"):
        raise vol.Invalid("Enter a hostname or IPv4 address, not a URL")
    try:
        ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        if not all(
            part and len(part) <= 63
            and part[0].isalnum()
            and part[-1].isalnum()
            and all(c.isalnum() or c == "-" for c in part)
            for part in host.split(".")
        ):
            raise vol.Invalid("Invalid hostname")
    return host


def user_form_schema() -> vol.Schema:
    """Return a schema compatible with HA's older form serialization.

    Only built-in Voluptuous validators/types belong in the schema. Hostname
    validation happens in normalize_host() when the form is submitted.
    """
    return vol.Schema(
        {
            vol.Required("host"): str,
            vol.Required("port", default=DEFAULT_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
        }
    )
