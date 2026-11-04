import unittest

from swarm_engine import (
    DEFAULT_AGENT_REGISTRY, build_swarm_plan, execute_swarm, load_agent_registry,
    redact_sensitive_text,
)

class SwarmEngineTests(unittest.TestCase):
    def test_registry_teams_reference_existing_agents(self):
        ids = {a["id"] for a in DEFAULT_AGENT_REGISTRY["agents"]}
        for team in DEFAULT_AGENT_REGISTRY["teams"].values():
            self.assertTrue(team)
            self.assertTrue(set(team).issubset(ids))

    def test_configured_registry_loads(self):
        registry = load_agent_registry("agent_registry.json")
        self.assertGreaterEqual(len(registry["agents"]), 20)
        self.assertIn("cvpen_cv_creation", registry["teams"])

    def test_swarm_is_bounded_and_ordered(self):
        plan = build_swarm_plan("cvpen_cv_creation", max_agents=3)
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]["execution_stage"], "produce")
        self.assertEqual(plan[-1]["execution_stage"], "finalize")

    def test_unknown_task_falls_back_to_research_team(self):
        self.assertEqual(build_swarm_plan("unknown")[0]["id"], "research_analyst")

    def test_invalid_max_agents_rejected(self):
        with self.assertRaises(ValueError):
            build_swarm_plan("research", max_agents=0)

    def test_execute_swarm_invokes_each_agent_and_returns_final(self):
        calls = []
        seen_contexts = []
        def fake_call(agent, instruction, context):
            calls.append(agent["id"])
            seen_contexts.append(context)
            return "draft" if len(calls) == 1 else ("review" if len(calls) == 2 else "final")
        result = execute_swarm({"task_type":"social_post_draft"}, fake_call, max_agents=3)
        self.assertEqual(len(calls), 3)
        self.assertIn("Agents invoked: 3", result)
        self.assertTrue(result.endswith("final"))
        self.assertIn("draft", seen_contexts[1])
        self.assertIn("draft", seen_contexts[2])
        self.assertIn("review", seen_contexts[2])

    def test_empty_agent_output_fails_closed(self):
        def fake_call(agent, instruction, context):
            return ""
        with self.assertRaises(RuntimeError):
            execute_swarm({"task_type":"research"}, fake_call)

    def test_memory_redaction_removes_common_pii_and_secrets(self):
        value = "Mail a@example.com phone 01012345678 ID 12345678901234 key sk-abcdefghijklmnop"
        redacted = redact_sensitive_text(value)
        self.assertNotIn("a@example.com", redacted)
        self.assertNotIn("01012345678", redacted)
        self.assertNotIn("12345678901234", redacted)
        self.assertNotIn("sk-abcdefghijklmnop", redacted)

if __name__ == "__main__":
    unittest.main()
