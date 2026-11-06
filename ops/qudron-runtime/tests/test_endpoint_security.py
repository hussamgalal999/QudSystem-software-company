import unittest

from urllib.request import Request

from endpoint_security import (
    RejectCredentialRedirectHandler, is_allowed_credential_endpoint,
    open_credential_request,
)


class CredentialEndpointPolicyTests(unittest.TestCase):
    def test_https_is_allowed_without_userinfo_or_query_secrets(self):
        self.assertTrue(is_allowed_credential_endpoint("https://memory.example.com/v1"))
        self.assertFalse(is_allowed_credential_endpoint("https://user:pass@memory.example.com/v1"))
        self.assertFalse(is_allowed_credential_endpoint("https://memory.example.com/v1?token=secret"))

    def test_only_exact_localhost_and_loopback_ip_are_allowed_over_http(self):
        for url in (
            "http://localhost:8765/mcp",
            "http://127.0.0.1:8765/mcp",
            "http://127.0.0.2:8765/mcp",
            "http://[::1]:8765/mcp",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_allowed_credential_endpoint(url))

    def test_lookalike_hosts_and_non_loopback_addresses_are_rejected(self):
        for url in (
            "http://localhost.evil.test/mcp",
            "http://localhost.attacker.example/mcp",
            "http://127.0.0.1.evil.test/mcp",
            "http://192.168.1.10:8765/mcp",
            "http://user:pass@127.0.0.1:8765/mcp",
            "file:///etc/passwd",
            "http://localhost:99999/mcp",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_allowed_credential_endpoint(url))



class CredentialRedirectPolicyTests(unittest.TestCase):
    def test_authorized_request_redirects_are_rejected(self):
        handler = RejectCredentialRedirectHandler()
        request = Request("https://api.example.com/v1/tasks")
        redirected = handler.redirect_request(
            request, None, 302, "Found", {"Location": "https://attacker.example/collect"},
            "https://attacker.example/collect",
        )
        self.assertIsNone(redirected)

    def test_open_credential_request_requires_an_allowed_endpoint(self):
        request = Request("http://remote.example/v1/tasks")
        with self.assertRaisesRegex(ValueError, "endpoint is not allowed"):
            open_credential_request(request, timeout=2)


if __name__ == "__main__":
    unittest.main()
