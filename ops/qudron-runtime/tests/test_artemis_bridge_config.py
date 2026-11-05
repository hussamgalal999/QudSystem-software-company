import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artemis_bridge import _artemis_project_root, _safe_artifact


class ArtemisBridgeConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "artemis"
        (self.root / "traces").mkdir(parents=True)
        self.config = Path(self.temp.name) / "bridge.json"
        self.config.write_text(json.dumps({"mcp": {"cwd": str(self.root)}}), encoding="utf-8")
        self.env = patch.dict(os.environ, {
            "ARTEMIS_BRIDGE_CONFIG": str(self.config),
            "ARTEMIS_MCP_CWD": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_project_root_uses_json_config_when_env_override_is_absent(self):
        self.assertEqual(_artemis_project_root(), self.root.resolve())

    def test_trace_image_is_read_from_configured_artemis_tree(self):
        image = self.root / "traces" / "battery.png"
        image.write_bytes(b"test-image")
        result = _safe_artifact(image.as_uri())
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["mimeType"], "image/png")

    def test_image_outside_artemis_tree_is_not_returned(self):
        outside = Path(self.temp.name) / "private.png"
        outside.write_bytes(b"must-not-leak")
        self.assertIsNone(_safe_artifact(outside.as_uri()))


if __name__ == "__main__":
    unittest.main()
