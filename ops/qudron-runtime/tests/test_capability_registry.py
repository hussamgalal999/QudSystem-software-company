import tempfile
import unittest
from pathlib import Path

from capability_registry import (
    CapabilityRegistryError, add_relation, find_alternatives,
    get_capability, initialize_registry, list_stale_capabilities,
    register_capability, search_capabilities,
)


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "registry.sqlite3"
        initialize_registry(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, cid, **extra):
        data = {"id": cid, "kind": "tool", "name": cid, "status": "verified",
                "trust_score": 80, "verified_at": "2026-11-04T10:00:00+00:00",
                "tags": ["browser", "automation"]}
        data.update(extra)
        return data

    def test_upsert_and_get(self):
        register_capability(self.db, self.item("browser.one"))
        updated = register_capability(self.db, self.item("browser.one", name="Browser One"))
        self.assertEqual(updated["name"], "Browser One")
        self.assertEqual(get_capability(self.db, "browser.one")["tags"], ["automation", "browser"])

    def test_search_filters_kind_status_and_query(self):
        register_capability(self.db, self.item("browser.one", name="Browser One"))
        register_capability(self.db, self.item("model.one", kind="model", name="Model One"))
        self.assertEqual(len(search_capabilities(self.db, "browser", kind="tool")), 1)
        self.assertEqual([x["id"] for x in search_capabilities(self.db, kind="model")], ["model.one"])

    def test_unverified_discovery_not_returned_by_default(self):
        register_capability(self.db, self.item("tool.new", status="discovered"))
        self.assertEqual(search_capabilities(self.db), [])

    def test_alternatives_explicit_then_same_kind_fallback(self):
        register_capability(self.db, self.item("tool.a"))
        register_capability(self.db, self.item("tool.b", trust_score=90))
        register_capability(self.db, self.item("tool.c", trust_score=70))
        add_relation(self.db, "tool.a", "tool.c")
        self.assertEqual([x["id"] for x in find_alternatives(self.db, "tool.a", 2)],
                         ["tool.c", "tool.b"])

    def test_stale_verification_detected(self):
        register_capability(self.db, self.item("tool.old", verified_at="2026-01-01T00:00:00+00:00"))
        self.assertEqual([x["id"] for x in list_stale_capabilities(self.db, "2026-10-01T00:00:00+00:00")],
                         ["tool.old"])

    def test_rejects_unsafe_or_invalid_metadata(self):
        with self.assertRaises(CapabilityRegistryError):
            register_capability(self.db, self.item("../escape"))
        with self.assertRaises(CapabilityRegistryError):
            register_capability(self.db, self.item("tool.bad", trust_score=101))
        with self.assertRaises(CapabilityRegistryError):
            register_capability(self.db, self.item("tool.bad", metadata={"x": "y" * 70000}))


if __name__ == "__main__":
    unittest.main()
