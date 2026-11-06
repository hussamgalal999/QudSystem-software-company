"""Strict URL checks for endpoints that receive Qudron bearer credentials."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_allowed_credential_endpoint(url: str) -> bool:
    """Allow HTTPS endpoints or exact HTTP loopback hosts only.

    Prefix checks are unsafe here: 127.0.0.1.attacker.example and
    localhost.attacker.example are remote hosts, not loopback destinations.
    """
    if not isinstance(url, str) or not url or url != url.strip():
        return False
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        # Reject user-info, fragments, query credentials, missing hosts and
        # malformed ports before any bearer token can be attached.
        if (
            not hostname or not parsed.netloc
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
        ):
            return False
        _ = parsed.port  # Trigger ValueError for invalid port syntax/ranges.
    except ValueError:
        return False

    if parsed.scheme.lower() == "https":
        return True
    if parsed.scheme.lower() != "http":
        return False
    if hostname == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        return False
    # Any IP address classified by the standard library as loopback is
    # local-only; non-loopback private/LAN addresses remain disallowed.
    return address.is_loopback
