import json
import unittest
from pathlib import Path

class CVPenWorkflowTests(unittest.TestCase):
    def test_paid_cv_workflow_has_payment_gate_before_cv_creation(self):
        data = json.loads(Path("service_workflows.json").read_text(encoding="utf-8"))
        workflow = data["workflows"]["cvpen_order"]
        steps = workflow["steps"]
        ids = [step["id"] for step in steps]
        self.assertEqual(workflow["status"], "DESIGNED_NOT_CONNECTED")
        self.assertLess(ids.index("payment_confirmation"), ids.index("career_strategy"))
        self.assertLess(ids.index("fact_review"), ids.index("delivery"))
        payment_gate = next(s["gate"] for s in steps if s["id"] == "payment_confirmation").lower()
        self.assertIn("provider-authenticated webhook", payment_gate)
        self.assertIn("sms", payment_gate)
        self.assertIn("not sufficient", payment_gate)
        self.assertGreaterEqual(len(workflow["non_negotiable_invariants"]), 4)

if __name__ == "__main__":
    unittest.main()
