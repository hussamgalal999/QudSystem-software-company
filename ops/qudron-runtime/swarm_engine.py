"""Qudron bounded multi-agent orchestration primitives.

Agents are role prompts routed through model profiles; they are not separate
human workers or separately hosted models unless the operator configures them.
"""
from __future__ import annotations

import json
import re
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
        {"id":"strategy_council","name":"Strategy Council","profile":"reasoning","stage":"draft","responsibilities":"Compare options, constraints, and downside scenarios."}
    ],
    "teams": {
        "research":["research_analyst","evidence_checker"],
        "social_post_draft":["brand_strategist","copywriter","brand_quality"],
        "video_script":["video_producer","localization_specialist","creative_qa"],
        "translation":["localization_specialist","language_qa"],
        "seo_plan":["seo_strategist","technical_seo","evidence_checker"],
        "lead_research":["market_research","sales_qualifier","privacy_qa"],
        "cvpen_cv_creation":["career_strategist","cv_writer","ats_specialist","fact_checker","cv_qa"],
        "cvpen_ats_audit":["ats_specialist","fact_checker","cv_qa"],
        "customer_support_reply":["customer_success","policy_checker","brand_quality"],
        "payment_reconciliation":["finance_ops","payment_verifier","compliance_reviewer"],
        "product_review":["product_manager","data_analyst","qa_engineer"],
        "engineering_review":["software_engineer","reliability_engineer","qa_engineer"],
        "strategy_review":["strategy_council","data_analyst","evidence_checker"]
    }
}

def load_agent_registry(path: str | Path | None = None) -> dict[str, Any]:
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

def build_swarm_plan(task_type: str, registry: dict[str, Any] | None = None,
                     max_agents: int = 3) -> list[dict[str, Any]]:
    if max_agents < 1:
        raise ValueError("max_agents must be >= 1")
    registry = registry or DEFAULT_AGENT_REGISTRY
    by_id = {agent["id"]: agent for agent in registry["agents"]}
    team = registry["teams"].get(task_type) or registry["teams"].get("research")
    if not team:
        raise ValueError(f"No agents configured for task type: {task_type}")
    selected = team[:max_agents]
    plan = [dict(by_id[agent_id]) for agent_id in selected]
    for index, agent in enumerate(plan):
        if index == 0:
            agent["execution_stage"] = "produce"
        elif index == len(plan) - 1:
            agent["execution_stage"] = "finalize"
        else:
            agent["execution_stage"] = "review"
    return plan

def execute_swarm(task: dict[str, Any], call_agent: Callable[[dict[str, Any], str, str], str],
                  registry: dict[str, Any] | None = None, memory_context: str = "",
                  max_agents: int = 3, max_context_chars: int = 12000) -> str:
    plan = build_swarm_plan(str(task.get("task_type", "research")), registry, max_agents)
    prior = ""
    final_output = ""
    for index, agent in enumerate(plan):
        stage = agent["execution_stage"]
        if stage == "produce":
            instruction = (
                "Produce the requested deliverable. Be specific, useful, and honest. "
                "Separate verified facts from assumptions and unknowns. Do not claim external actions."
            )
            context = memory_context
        elif stage == "review":
            instruction = (
                "Independently audit the draft. Identify factual gaps, missing requirements, risks, "
                "privacy issues, contradictions, and concrete corrections. Do not invent evidence."
            )
            context = (memory_context + "\n\nDRAFT TO REVIEW:\n" + prior)[-max_context_chars:]
        else:
            instruction = (
                "Create the final corrected deliverable using the original task, draft, and review. "
                "Resolve only issues supported by the supplied information; list unresolved checks. "
                "Do not include hidden reasoning or claim tests/actions were performed unless evidenced."
            )
            context = (memory_context + "\n\nDRAFT AND REVIEW:\n" + prior)[-max_context_chars:]
        response = call_agent(agent, instruction, context)
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError(f"Agent returned empty output: {agent['id']}")
        prior = response.strip()[-max_context_chars:]
        final_output = prior
    team_names = " → ".join(agent["name"] for agent in plan)
    return f"## Qudron swarm\nTeam: {team_names}\nAgents invoked: {len(plan)}\n\n{final_output}"

def redact_sensitive_text(value: str) -> str:
    """Best-effort redaction before operational text is persisted in shared memory."""
    text = str(value)
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text)
    text = re.sub(r"(?<!\d)(?:\+?20|0)?1[0125]\d{8}(?!\d)", "[REDACTED_PHONE]", text)
    text = re.sub(r"(?<!\d)\d{14}(?!\d)", "[REDACTED_NATIONAL_ID]", text)
    text = re.sub(r"(?<!\d)\d{13,19}(?!\d)", "[REDACTED_PAYMENT_NUMBER]", text)
    text = re.sub(r"(?i)\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,})\b", "[REDACTED_SECRET]", text)
    return text
