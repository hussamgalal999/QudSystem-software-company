import copy
import json
import unittest
from pathlib import Path

from quality_contract_validator import (
    parse_profile_gates,
    validate_registry,
    validate_task_contract,
)

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
REGISTRY_PATH = ROOT / "project_task_registry.json"
FRAMEWORK_PATH = REPO / "docs" / "QUALITY_VERIFICATION_FRAMEWORK.md"


class QualityContractValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.framework = FRAMEWORK_PATH.read_text(encoding="utf-8")
        cls.profiles = parse_profile_gates(cls.framework)

    def test_all_registry_tasks_have_valid_machine_enforced_contracts(self):
        self.assertEqual(validate_registry(self.registry, self.framework), [])

    def test_unknown_gate_id_is_rejected(self):
        task = copy.deepcopy(self.registry["tasks"][0])
        task["mandatory_gates"][0] = "invented_gate"
        self.assertTrue(any("unknown canonical" in e or "subset" in e
                            for e in validate_task_contract(task, self.profiles)))

    def test_missing_weight_and_invalid_weight_sum_are_rejected(self):
        task = copy.deepcopy(self.registry["tasks"][0])
        task["gate_weights"].pop(task["mandatory_gates"][0])
        self.assertTrue(any("keys must exactly match" in e
                            for e in validate_task_contract(task, self.profiles)))
        task = copy.deepcopy(self.registry["tasks"][0])
        first = task["mandatory_gates"][0]
        task["gate_weights"][first] += 5
        self.assertTrue(any("sum to 100" in e
                            for e in validate_task_contract(task, self.profiles)))

    def test_critical_gate_must_be_mandatory_and_declared(self):
        task = copy.deepcopy(self.registry["tasks"][0])
        task["critical_gates"] = ["not_a_gate"]
        self.assertTrue(any("critical_gates must be a subset" in e
                            for e in validate_task_contract(task, self.profiles)))

    def test_invalid_or_below_minimum_maturity_is_rejected(self):
        task = copy.deepcopy(self.registry["tasks"][0])
        task["required_maturity"] = "M8"
        self.assertTrue(any("M0-M7" in e
                            for e in validate_task_contract(task, self.profiles)))
        task["required_maturity"] = "M2"
        self.assertTrue(any("requires at least" in e
                            for e in validate_task_contract(task, self.profiles)))


if __name__ == "__main__":
    unittest.main()
