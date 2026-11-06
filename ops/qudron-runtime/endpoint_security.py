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
        if "%" in hostname:
        return False
    address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    # Any IP address classified by the standard library as loopback is
    # local-only; non-loopback private/LAN addresses remain disallowed.
    return address.is_loopback



from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class RejectCredentialRedirectHandler(HTTPRedirectHandler):
    """Reject all redirects for requests carrying provider or owner credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_credential_request(
    request: Request, *, timeout: float = 30, endpoint_validated: bool = False
):
    """Open an authenticated request without forwarding credentials via redirects.

    By default, apply this module's HTTPS/exact-loopback policy. A caller may
    set endpoint_validated=True only after applying its own stricter provider
    URL validation (for example, the model router's exact Docker-service allowlist).
    A 3xx response is surfaced as HTTPError; it is never followed automatically.
    """
    if not isinstance(request, Request):
        raise TypeError("request must be urllib.request.Request")
    if not endpoint_validated and not is_allowed_credential_endpoint(request.full_url):
        raise ValueError("Credential request endpoint is not allowed")
    if urlsplit(request.full_url).scheme.lower() == "http":
        opener = build_opener(ProxyHandler({}), RejectCredentialRedirectHandler())
    else:
        opener = build_opener(RejectCredentialRedirectHandler())
    return opener.open(request, timeout=max(1, min(300, float(timeout))))
