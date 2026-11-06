import unittest

from endpoint_security import is_allowed_credential_endpoint


class CredentialEndpointPolicyTests(unittest.TestCase):
    def test_https_is_allowed_without_userinfo_or_query_secrets(self):
        self.assertTrue(is_allowed_credential_endpoint("https://memory.example.com/v1"))
        self.assertFalse(is_allowed_credential_endpoint("https://user:pass@memory.example.com/v1"))
        self.assertFalse(is_allowed_credential_endpoint("https://memory.example.com/v1?token=secret"))

    def test_only_exact_localhost_and_loopback_ip_are_allowed_over_http(self):
        for url in (
            "http://localhost:8765/mcp",
            "http://127.0.0.1:8765/mcp",
            "http://[::1]:8765/mcp",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_allowed_credential_endpoint(url))

    def test_lookalike_hosts_and_non_loopback_addresses_are_rejected(self):
        for url in (
            "http://localhost.evil.test/mcp",
            "http://localhost.attacker.example/mcp",
            "http://127.0.0.1.evil.test/mcp",
            "http://127.0.0.2:8765/mcp",
            "http://192.168.1.10:8765/mcp",
            "http://user:pass@127.0.0.1:8765/mcp",
            "file:///etc/passwd",
            "http://localhost:99999/mcp",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_allowed_credential_endpoint(url))


if __name__ == "__main__":
    unittest.main()
