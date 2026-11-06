import unittest
import threading

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

    def test_qudron_registry_has_40_specialist_roles_and_core_teams(self):
        registry = load_agent_registry("agent_registry.json")
        self.assertEqual(len(registry["agents"]), 40)
        ids = {agent["id"] for agent in registry["agents"]}
        self.assertTrue(set(registry["teams"]["qudron_core_delivery"]).issubset(ids))
        self.assertTrue(set(registry["teams"]["qudron_control_plane"]).issubset(ids))
        self.assertEqual(len(registry["teams"]["qudron_core_delivery"]), 5)
        self.assertEqual(len(registry["teams"]["qudron_control_plane"]), 5)

    def test_eight_qudron_waves_assign_all_40_specialists_once(self):
        registry = load_agent_registry("agent_registry.json")
        wave_teams = {
            name: members for name, members in registry["teams"].items()
            if name.startswith("qudron_wave_")
        }
        assigned = [agent_id for members in wave_teams.values() for agent_id in members]
        self.assertEqual(len(wave_teams), 8)
        self.assertEqual(len(assigned), 40)
        self.assertEqual(len(set(assigned)), 40)
        self.assertEqual({agent["id"] for agent in registry["agents"]}, set(assigned))
        for members in wave_teams.values():
            self.assertEqual(len(members), 5)

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


    def test_five_agent_cvpen_swarm_aggregates_all_independent_reviews(self):
        calls = []
        contexts = {}
        lock = threading.Lock()
        def fake_call(agent, instruction, context):
            with lock:
                calls.append(agent["id"])
            if agent["execution_stage"] == "produce":
                return "initial draft"
            if agent["execution_stage"] == "review":
                contexts[agent["id"]] = context
                return f"review finding {agent['id']}"
            contexts["finalizer"] = context
            return "final corrected CV"
        result = execute_swarm(
            {"task_type":"cvpen_cv_creation"},
            fake_call,
            max_agents=5
        )
        self.assertEqual(len(calls), 5)
        self.assertTrue(result.endswith("final corrected CV"))
        self.assertIn("initial draft", contexts["career_strategist"])
        self.assertIn("initial draft", contexts["ats_specialist"])
        self.assertIn("initial draft", contexts["fact_checker"])
        for reviewer_id in ("career_strategist", "ats_specialist", "fact_checker"):
            self.assertIn(f"review finding {reviewer_id}", contexts["finalizer"])

    def test_cvpen_ten_agent_team_has_one_writer_eight_reviewers_and_final_qa(self):
        registry = load_agent_registry("agent_registry.json")
        team = registry["teams"]["cvpen_cv_creation"]
        plan = build_swarm_plan("cvpen_cv_creation", registry=registry, max_agents=10)
        self.assertEqual(len(team), 10)
        self.assertEqual(len(plan), 10)
        self.assertEqual(plan[0]["id"], "cv_writer")
        self.assertEqual(plan[0]["execution_stage"], "produce")
        self.assertEqual(sum(a["execution_stage"] == "review" for a in plan), 8)
        self.assertEqual(plan[-1]["id"], "cv_qa")
        self.assertEqual(plan[-1]["execution_stage"], "finalize")

    def test_cvpen_reviews_run_concurrently_and_final_qa_receives_all_eight_notes(self):
        registry = load_agent_registry("agent_registry.json")
        review_barrier = threading.Barrier(8)
        lock = threading.Lock()
        reviewer_ids = []
        final_context = {"value":""}

        def fake_call(agent, instruction, context):
            stage = agent["execution_stage"]
            if stage == "produce":
                return "CV draft built only from user-confirmed source facts."
            if stage == "review":
                with lock:
                    reviewer_ids.append(agent["id"])
                review_barrier.wait(timeout=4)
                return f"verified review note from {agent['id']}"
            final_context["value"] = context
            return "final CV passed the bounded review gates"

        result = execute_swarm(
            {"task_type":"cvpen_cv_creation"},
            fake_call,
            registry=registry,
            max_agents=10,
            max_parallel_reviews=8
        )
        self.assertEqual(len(reviewer_ids), 8)
        self.assertIn("Agents invoked: 10", result)
        self.assertIn("Independent reviews: 8", result)
        self.assertTrue(result.endswith("final CV passed the bounded review gates"))
        for reviewer_id in reviewer_ids:
            self.assertIn(f"verified review note from {reviewer_id}", final_context["value"])

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
