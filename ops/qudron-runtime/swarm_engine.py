"""Qudron bounded multi-agent orchestration primitives.

Agents are role prompts routed through model profiles; they are not separate
human workers or separately hosted models unless the operator configures them.
"""
from __future__ import annotations

import json
import re
import concurrent.futures
from pathlib import Path
from typing import Any, Callable

DEFAULT_AGENT_REGISTRY = {
    "agents": [
        {"id":"research_analyst","name":"Research Analyst","profile":"balanced","stage":"draft","responsibilities":"Research and synthesize; separate facts, inference, and unknowns."},
        {"id":"evidence_checker","name":"Evidence Auditor","profile":"balanced","stage":"finalize","responsibilities":"Check evidence, uncertainty, unsupported claims, and verification notes."},
        {"id":"brand_strategist","name":"Brand Strategist","profile":"balanced","stage":"draft","responsibilities":"Protect brand positioning and customer trust."},
        {"id":"copywriter","name":"Conversion Copywriter","profile":"balanced","stage":"draft","responsibilities":"Write audience-focused copy with clear CTA."},
        {"id":"brand_quality","name":"Brand QA","profile":"balanced","stage":"finalize","responsibilities":"Review tone, clarity, proof, and brand consistency."},
        {"id":"video_producer","name":"Video Producer","profile":"balanced","stage":"draft","responsibilities":"Create feasible short-form scripts and shot lists."},
        {"id":"localization_specialist","name":"Localization Specialist","profile":"balanced","stage":"review","responsibilities":"Localize Arabic and English naturally."},
        {"id":"creative_qa","name":"Creative QA","profile":"balanced","stage":"finalize","responsibilities":"Review timing, subtitles, story, and CTA."},
        {"id":"language_qa","name":"Language QA","profile":"balanced","stage":"finalize","responsibilities":"Review grammar and meaning preservation."},
        {"id":"seo_strategist","name":"SEO Strategist","profile":"balanced","stage":"draft","responsibilities":"Map search intent and organic content."},
        {"id":"technical_seo","name":"Technical SEO","profile":"balanced","stage":"review","responsibilities":"Review technical SEO feasibility and risks."},
        {"id":"market_research","name":"Market Research","profile":"balanced","stage":"draft","responsibilities":"Find customer segments and market evidence."},
        {"id":"sales_qualifier","name":"Sales Qualifier","profile":"balanced","stage":"review","responsibilities":"Define fit and ethical outreach."},
        {"id":"privacy_qa","name":"Privacy QA","profile":"balanced","stage":"finalize","responsibilities":"Minimize personal data and prevent spam."},
        {"id":"customer_success","name":"Customer Success","profile":"balanced","stage":"draft","responsibilities":"Prepare clear customer-facing service communication."},
        {"id":"policy_checker","name":"Policy Checker","profile":"balanced","stage":"review","responsibilities":"Check commitments, terms, and service boundaries."},
        {"id":"career_strategist","name":"Career Strategist","profile":"reasoning","stage":"draft","responsibilities":"Map confirmed client facts to target role."},
        {"id":"cv_writer","name":"ATS CV Writer","profile":"balanced","stage":"draft","responsibilities":"Write evidence-based CV content only from supplied facts."},
        {"id":"ats_specialist","name":"ATS Specialist","profile":"balanced","stage":"review","responsibilities":"Review parseability, structure, headings, and relevant keywords."},
        {"id":"fact_checker","name":"Fact Checker","profile":"reasoning","stage":"review","responsibilities":"Flag every unsupported career claim and inconsistency."},
        {"id":"cv_qa","name":"CV Final QA","profile":"balanced","stage":"finalize","responsibilities":"Check completeness, privacy, readability, and delivery readiness."},
        {"id":"finance_ops","name":"Finance Ops","profile":"balanced","stage":"draft","responsibilities":"Reconcile expected amounts and identify discrepancies; never transfer funds."},
        {"id":"payment_verifier","name":"Payment Evidence Reviewer","profile":"reasoning","stage":"review","responsibilities":"Review provider-authenticated transaction evidence, not SMS alone."},
        {"id":"compliance_reviewer","name":"Compliance Reviewer","profile":"reasoning","stage":"finalize","responsibilities":"Check authorization, privacy, fraud, and audit requirements."},
        {"id":"product_manager","name":"Product Manager","profile":"balanced","stage":"draft","responsibilities":"Define acceptance criteria and product priorities."},
        {"id":"software_engineer","name":"Software Engineer","profile":"reasoning","stage":"draft","responsibilities":"Design secure APIs, webhooks, and integrations."},
        {"id":"reliability_engineer","name":"Reliability Engineer","profile":"reasoning","stage":"review","responsibilities":"Review retries, recovery, monitoring, and failure modes."},
        {"id":"qa_engineer","name":"QA Engineer","profile":"balanced","stage":"finalize","responsibilities":"Write and validate test plans and release gates."},
        {"id":"data_analyst","name":"Data Analyst","profile":"balanced","stage":"review","responsibilities":"Analyze real measurements only; identify missing data."},
        {"id":"strategy_council","name":"Strategy Council","profile":"reasoning","stage":"draft","responsibilities":"Compare options, constraints, and downside scenarios."},
        {"id":"cv_grammar_editor","name":"CV Grammar & Localization Reviewer","profile":"fast","stage":"review","responsibilities":"Review Arabic/English grammar, spelling, verb tense, terminology and translation consistency while preserving all source facts."},
        {"id":"cv_role_match_reviewer","name":"Target-Role Alignment Reviewer","profile":"balanced","stage":"review","responsibilities":"Map target-job requirements to evidence actually supplied by the candidate; flag unsupported matches and genuine gaps."},
        {"id":"cv_achievement_reviewer","name":"Achievement Evidence Reviewer","profile":"fast","stage":"review","responsibilities":"Improve clarity and action verbs; verify every number and outcome has candidate-provided evidence; never invent metrics."},
        {"id":"cv_readability_reviewer","name":"CV Readability & Layout Reviewer","profile":"fast","stage":"review","responsibilities":"Check skimmability, section order, hierarchy, text density and ATS-safe structure; do not claim to have rendered or inspected final PDF geometry."},
        {"id":"cv_privacy_reviewer","name":"CV Privacy Reviewer","profile":"reasoning","stage":"review","responsibilities":"Flag unnecessary national IDs, full addresses, sensitive disclosures and excess personal data while preserving contact information genuinely needed for applications."}
    ],
    "teams": {
        "research":["research_analyst","evidence_checker"],
        "social_post_draft":["brand_strategist","copywriter","brand_quality"],
        "video_script":["video_producer","localization_specialist","creative_qa"],
        "translation":["localization_specialist","language_qa"],
        "seo_plan":["seo_strategist","technical_seo","evidence_checker"],
        "lead_research":["market_research","sales_qualifier","privacy_qa"],
        "cvpen_cv_creation":["cv_writer","career_strategist","ats_specialist","fact_checker","cv_grammar_editor","cv_role_match_reviewer","cv_achievement_reviewer","cv_readability_reviewer","cv_privacy_reviewer","cv_qa"],
        "cvpen_ats_audit":["ats_specialist","fact_checker","cv_qa"],
        "customer_support_reply":["customer_success","policy_checker","brand_quality"],
        "payment_reconciliation":["finance_ops","payment_verifier","compliance_reviewer"],
        "product_review":["product_manager","data_analyst","qa_engineer"],
        "engineering_review":["software_engineer","reliability_engineer","qa_engineer"],
        "strategy_review":["strategy_council","data_analyst","evidence_checker"],
        "risk_review":["compliance_reviewer","privacy_qa","reliability_engineer"],
        "incident_triage":["reliability_engineer","qa_engineer","evidence_checker"]
    }
}

def load_agent_registry(path: str | Path | None = None) -> dict[str, Any]:
    if path is not None:
        p = Path(path)
        if not p.exists():
            candidate = Path(__file__).resolve().parent / p
            if candidate.exists():
                path = candidate
    if path is None or not Path(path).exists():
        return DEFAULT_AGENT_REGISTRY
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    agents = raw.get("agents")
    teams = raw.get("teams")
    if not isinstance(agents, list) or not isinstance(teams, dict):
        raise ValueError("Agent registry must contain agents[] and teams{}")
    ids = {item.get("id") for item in agents if isinstance(item, dict)}
    if len(ids) != len(agents) or None in ids:
        raise ValueError("Agent IDs must be present and unique")
    for team, members in teams.items():
        if not isinstance(members, list) or not members or any(member not in ids for member in members):
            raise ValueError(f"Invalid or empty team: {team}")
    return raw

# Cross-functional reviewers used to complete a ten-role quality panel when a
# task-specific team is smaller. Domain producer/finalizer roles are preserved.
CROSS_FUNCTIONAL_REVIEWER_IDS = (
    "evidence_checker",
    "privacy_qa",
    "policy_checker",
    "fact_checker",
    "qa_engineer",
    "reliability_engineer",
    "data_analyst",
    "strategy_council",
    "compliance_reviewer",
)


def build_swarm_plan(task_type: str, registry: dict[str, Any] | None = None,
                     max_agents: int | None = None) -> list[dict[str, Any]]:
    """Plan at least ten distinct roles by default, with bounded review fan-out.

    All domain roles in the selected team are retained unless an explicit
    task-scoped max_agents cap is supplied. Shorter teams are extended with
    cross-functional reviewers; role definitions are not claims of live model
    sessions or separate worker processes.
    """
    if max_agents is not None and max_agents < 1:
        raise ValueError("max_agents must be >= 1")
    registry = registry or DEFAULT_AGENT_REGISTRY
    by_id = {agent["id"]: agent for agent in registry["agents"]}
    team = registry["teams"].get(task_type) or registry["teams"].get("research")
    if not team:
        raise ValueError(f"No agents configured for task type: {task_type}")

    target_count = max(10, len(team))
    if max_agents is not None:
        target_count = min(target_count, max_agents)
    base = list(team[:target_count])
    if not base:
        raise ValueError(f"No agents selected for task type: {task_type}")
    if target_count == 1:
        plan = [dict(by_id[base[0]])]
        plan[0]["execution_stage"] = "produce"
        plan[0]["assignment_source"] = "task_team"
        return plan

    producer_id = base[0]
    if len(base) >= 2:
        finalizer_id = base[-1]
        reviewer_ids = list(base[1:-1])
    else:
        finalizer_id = None
        reviewer_ids = []

    if finalizer_id is None:
        finalizer_id = next(
            (role_id for role_id in reversed(CROSS_FUNCTIONAL_REVIEWER_IDS)
             if role_id in by_id and role_id != producer_id),
            None,
        )
    if finalizer_id is None:
        raise ValueError("Registry has no distinct finalizer role for the selected task")

    required_reviewers = target_count - 2
    used = {producer_id, finalizer_id, *reviewer_ids}
    supplemental_ids: set[str] = set()
    # Prefer the stable cross-functional QA panel, then draw from the
    # remaining registered specialists if a domain team overlaps that panel.
    candidate_ids = list(CROSS_FUNCTIONAL_REVIEWER_IDS)
    candidate_ids.extend(role_id for role_id in by_id if role_id not in candidate_ids)
    for role_id in candidate_ids:
        if len(reviewer_ids) >= required_reviewers:
            break
        if role_id in by_id and role_id not in used:
            reviewer_ids.append(role_id)
            used.add(role_id)
            if role_id not in base:
                supplemental_ids.add(role_id)

    if len(reviewer_ids) < required_reviewers:
        raise ValueError(
            f"Registry cannot supply {target_count} unique roles for task type: {task_type}"
        )

    selected = [producer_id, *reviewer_ids, finalizer_id]
    plan = [dict(by_id[agent_id]) for agent_id in selected]
    for index, agent in enumerate(plan):
        if index == 0:
            agent["execution_stage"] = "produce"
        elif index == len(plan) - 1:
            agent["execution_stage"] = "finalize"
        else:
            agent["execution_stage"] = "review"
        agent["assignment_source"] = (
            "cross_functional_review" if agent["id"] in supplemental_ids
            else "task_team"
        )
    return plan

def execute_swarm(task: dict[str, Any], call_agent: Callable[[dict[str, Any], str, str], str],
                  registry: dict[str, Any] | None = None, memory_context: str = "",
                  max_agents: int | None = None, max_context_chars: int = 12000,
                  max_parallel_reviews: int = 8) -> str:
    """Run the complete configured team with resource-bounded parallel reviews."""
    plan = build_swarm_plan(str(task.get("task_type", "research")), registry, max_agents)
    producer = next((agent for agent in plan if agent["execution_stage"] == "produce"), None)
    reviewers = [agent for agent in plan if agent["execution_stage"] == "review"]
    finalizer = next((agent for agent in plan if agent["execution_stage"] == "finalize"), None)

    if producer is None:
        raise RuntimeError("Swarm plan has no producer stage")

    produce_instruction = (
        "Produce the requested deliverable. Be specific, useful, and honest. "
        "Separate verified facts from assumptions and unknowns. Do not claim external actions."
    )
    draft_output = call_agent(producer, produce_instruction, memory_context)
    if not isinstance(draft_output, str) or not draft_output.strip():
        raise RuntimeError(f"Agent returned empty output: {producer['id']}")
    draft_output = draft_output.strip()[-max_context_chars:]

    review_outputs: list[tuple[dict[str, Any], str]] = []
    if reviewers:
        review_instruction = (
            "Independently audit the draft from your specialist perspective. Identify factual gaps, "
            "missing requirements, risks, privacy issues, contradictions, accessibility or parsing "
            "problems, and concrete corrections. Do not invent evidence. Do not repeat another "
            "reviewer's work; return distinct, actionable findings. This is a review, not a rewrite "
            "of facts unsupported by the source."
        )
        review_context = (
            memory_context[-3000:] + "\n\nDRAFT TO REVIEW:\n" + draft_output
        )[-max_context_chars:]
        worker_count = max(1, min(len(reviewers), max_parallel_reviews))
        results: dict[str, str] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="qudron-review"
        ) as pool:
            futures = {
                agent["id"]: pool.submit(
                    call_agent, agent, review_instruction, review_context
                )
                for agent in reviewers
            }
            for agent in reviewers:
                response = futures[agent["id"]].result()
                if not isinstance(response, str) or not response.strip():
                    raise RuntimeError(f"Reviewer returned empty output: {agent['id']}")
                results[agent["id"]] = response.strip()
        per_review_chars = max(
            500, min(2500, (max_context_chars - 4500) // max(1, len(reviewers)))
        )
        review_outputs = [
            (agent, results[agent["id"]][-per_review_chars:])
            for agent in reviewers
        ]

    if finalizer is not None:
        final_instruction = (
            "Create the final corrected deliverable using the original task, draft, and ALL "
            "independent review notes. Resolve only issues supported by supplied information; "
            "list unresolved checks and verification gates. Do not expose hidden reasoning or claim "
            "tests/actions were performed unless evidenced."
        )
        review_sections = [
            f"REVIEW — {agent['name']} ({agent['id']}):\n{note}"
            for agent, note in review_outputs
        ]
        final_context = (
            "RELEVANT MEMORY:\n" + memory_context[-1500:]
            + "\n\nINITIAL DRAFT:\n" + draft_output[-2500:]
            + "\n\nINDEPENDENT REVIEW NOTES:\n"
            + ("\n\n".join(review_sections) if review_sections else "[no separate review stage]")
        )[-max_context_chars:]
        final_output = call_agent(finalizer, final_instruction, final_context)
        if not isinstance(final_output, str) or not final_output.strip():
            raise RuntimeError(f"Finalizer returned empty output: {finalizer['id']}")
        final_output = final_output.strip()[-max_context_chars:]
    else:
        final_output = (
            draft_output + (
                "\n\nREVIEW NOTES:\n" + "\n\n".join(note for _, note in review_outputs)
                if review_outputs else ""
            )
        )

    team_names = " → ".join(agent["name"] for agent in plan)
    return (
        f"## Qudron swarm\nTeam: {team_names}\n"
        f"Agents invoked: {len(plan)}\n"
        f"Independent reviews: {len(review_outputs)}\n\n{final_output}"
    )

def redact_sensitive_text(value: str) -> str:
    """Best-effort redaction before operational text is persisted in shared memory."""
    text = str(value)
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text)
    text = re.sub(r"(?<!\d)(?:\+?20|0)?1[0125]\d{8}(?!\d)", "[REDACTED_PHONE]", text)
    # Also redact common internationally formatted numbers, e.g. +1 555 123 4567.
    # Also cover parenthesized area codes such as (415) 555-2671.
    text = re.sub(
        r"(?<!\w)(?:\+\d{1,3}[\s.-]+(?:\(\d{2,4}\)|\d{2,4})[\s.-]+\d{3,4}[\s.-]*\d{3,4}|\(\d{3}\)[\s.-]*\d{3}[\s.-]*\d{4}|\d{3}[\s.-]\d{3}[\s.-]\d{4})(?!\w)",
        "[REDACTED_PHONE]",
        text,
    )
    text = re.sub(r"(?<!\d)\d{14}(?!\d)", "[REDACTED_NATIONAL_ID]", text)
    text = re.sub(r"(?<!\d)\d{13,19}(?!\d)", "[REDACTED_PAYMENT_NUMBER]", text)
    text = re.sub(r"(?i)\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,})\b", "[REDACTED_SECRET]", text)
    return text
