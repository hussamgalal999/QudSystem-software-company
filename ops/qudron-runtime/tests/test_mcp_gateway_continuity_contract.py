import tempfile
import unittest
from pathlib import Path

from continuity_store import ContinuityStore
from mcp_gateway import TOOLS, handle_mcp_request


WAVE_TASK_TYPES = {
    "qudron_wave_01_architecture",
    "qudron_wave_02_runtime_models",
    "qudron_wave_03_security_governance",
    "qudron_wave_04_opendots_experience",
    "qudron_wave_05_platform_release",
    "qudron_wave_06_market_commercial",
    "qudron_wave_07_cvpen_product",
    "qudron_wave_08_quality_payment",
}


class MCPGatewayContinuityContractTests(unittest.TestCase):
    def test_wave_task_types_are_advertised_for_single_and_batch_submission(self):
        tools = {tool["name"]: tool for tool in TOOLS}
        single = set(tools["qudron_submit_job"]["inputSchema"]["properties"]["task_type"]["enum"])
        batch = set(
            tools["qudron_submit_batch"]["inputSchema"]["properties"]["jobs"]["items"]
            ["properties"]["task_type"]["enum"]
        )
        self.assertTrue(WAVE_TASK_TYPES.issubset(single))
        self.assertTrue(WAVE_TASK_TYPES.issubset(batch))

    def test_continuity_contract_does_not_claim_to_return_stage_output(self):
        tools = {tool["name"]: tool for tool in TOOLS}
        description = tools["qudron_get_continuity"]["description"].lower()
        self.assertIn("recent stage records", description)
        self.assertIn("checkpoint-presence indicators", description)
        self.assertIn("does not expose stored stage output", description)

    def test_continuity_callback_omits_real_checkpoint_output(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ContinuityStore(Path(directory) / "qudron.sqlite3")
            claim = store.begin_stage(
                job_id="job-12345678", project="qudron",
                agent_id="qa_engineer", stage="review",
            )
            store.complete_stage(
                job_id="job-12345678", project="qudron",
                agent_id="qa_engineer", stage="review",
                claim_token=claim["claim_token"],
                output="private-stage-output must never leave the store",
            )
            response = handle_mcp_request(
                {"jsonrpc": "2.0", "id": 31, "method": "tools/call",
                 "params": {"name": "qudron_get_continuity", "arguments": {}}},
                is_authorized=lambda: True,
                enqueue_job=lambda _: {},
                get_job=lambda _: {},
                get_job_result=lambda _: "",
                get_status=lambda: {},
                get_usage=lambda: {},
                get_continuity=store.snapshot,
            )
        body = response["result"]["content"][0]["text"]
        self.assertIn('"has_output": 1', body)
        self.assertIn('"status": "completed"', body)
        self.assertNotIn("private-stage-output", body)
        self.assertNotIn('"output"', body)


if __name__ == "__main__":
    unittest.main()
