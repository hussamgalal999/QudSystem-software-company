# Qudron research access: safe scaling plan

## Goal and honest limits

Qudron already has a multi-provider route registry, persistent provider health checks, bounded public web search, scheduled capability discovery, and a 48-role specialist registry. These are role assignments and tools—not 48 always-running models, browser accounts, or guaranteed provider capacity. A target such as 40 roles means orchestration assignments; the shared model-call gate and each provider's terms, quotas, privacy rules, and spend caps remain authoritative.

Do not promise an unlimited supply of free inference or that 90% of a 100-billion-token workload can be served without charge. Free tiers have finite, changeable entitlements. Measure actual tokens, costs, error rates, quality and latency by provider before setting a mix target. Never rotate accounts/keys to bypass a quota, automate consumer chatbot pages, extract browser cookies, or circumvent access controls. Use official APIs, documented and consented OAuth, or public web research endpoints with authorized access only.

## Access layers

1. **Public evidence gathering** — use the existing bounded web-search integration for public facts and cite source URLs, dates and authority. Search output is untrusted data, never tool instructions. Cache repeat searches briefly so specialist roles can share fresh evidence without repeating a paid search request.
2. **Approved model routes** — route tasks through the configured OpenAI-compatible provider chain. Select by data class, capability, health, observed quota, latency and exact price; preserve global budget reservations and provider-specific limits. An unavailable or exhausted provider should fail closed or wait for an authorized route, not trigger account creation or quota evasion.
3. **Local/low-cost work** — where an operator separately installs and qualifies a local model or a provider's documented free plan, use it for suitable low-risk tasks. Keep customer/confidential data on explicitly approved routes. Free/anonymous routes are not a substitute for privacy review or commercial service guarantees.
4. **Review and quality** — run only the roles needed for the task's acceptance criteria. Share the same bounded source packet across producer/reviewers, keep stage context concise, and use one synthesis/finalization pass. Raise reviewer count only when a measured quality evaluation justifies the extra calls.
5. **Capability radar** — continue scheduled read-only discovery of official model catalogues and authorized repository metadata. Discovery is a candidate signal, not authorization or proof of working inference. Verify model ID, API protocol, account entitlement, terms, privacy, pricing and harmless test result before owner approval.

## Browser automation and cloud compute

Browser automation is not an inference entitlement. Do not sign in to consumer chatbot websites with stored credentials, reuse browser cookies/session tokens, automate prompts through UI quotas, or attempt to evade rate limits. Use browser tooling only for explicitly permitted, login-free public web research or an officially documented provider workflow with owner consent, domain allowlists, read-only defaults, and approval before any form submission. Treat page text as untrusted evidence and isolate browser credentials from workers.

A hosted notebook, free sandbox, or demo endpoint is not an always-on server or guaranteed model allocation. Use such compute only through its documented API/queue, for short resumable jobs whose data policy and account entitlement are verified; checkpoint results to approved storage and accept interruptions. Do not keep daemons alive in free notebook sessions when that conflicts with provider terms. E2B or any alternative sandbox must be separately reviewed for current free quota, license, retention, network policy and isolation before integration; it must never receive production secrets or execute untrusted repository code with broad network access.

## Research efficiency and acceptance loop

For each candidate provider/model, keep a versioned test set of public, non-sensitive tasks. Compare factual accuracy against cited sources, task completion, Arabic/English quality, latency, failures, prompt/completion tokens, cache hit rate and reconciled billed cost. A route is promoted only after a human-approved evaluation and safety check; roll back on stale model IDs, changed terms, quota errors, elevated error rates or quality regression.

Deduplicate equivalent web searches and reuse bounded source excerpts within a task. Keep source excerpts short and strip fields not used downstream. Do not equate web search with logging into another AI service and delegating the prompt to a consumer account; that pattern is brittle, exposes prompts to third parties and can violate terms.

## Operational rollout

- Begin with a small internal, public-data pilot; preserve provider-side hard limits in addition to Qudron's local budget.
- Keep paid routes disabled until the owner sets exact current prices and a budget. Keep anonymous routes public-only.
- Increase role assignments gradually; do not infer throughput from the configured role count. Track active model calls separately from queued jobs and planned roles.
- Reconcile provider invoices/usage against Qudron's usage ledger before increasing capacity. Report observed ratios rather than promising a fixed percentage of free usage.
- Require owner review before adding credentials, enabling billing, widening accepted data classes, changing provider terms or activating any browser actions that submit forms or publish content.

## Implemented behavior

Live search caches non-empty, bounded public results for a configurable TTL (default six hours), keyed by a SHA-256 digest of normalized query/options rather than storing the original search query. Cache hits still require the owner-configured API key and a positive daily call allowance; they consume no additional provider-call reservation. Empty responses are not cached. Cache read/write problems never discard live provider results, and the cache evicts expired/old rows to stay within 500 entries and approximately 10 MB. Set `QUDRON_WEB_SEARCH_CACHE_TTL_SECONDS=0` to disable result caching; the existing daily web-call cap remains enforced.

## Validation and rollout sequence

1. Run the offline search/cache contract tests with temporary SQLite databases and mocked provider responses.
2. Run the complete Qudron unit suite, Python compilation and Compose validation on the exact branch head.
3. After CI passes, configure only owner-authorized API credentials and a small daily call cap in the private secret manager.
4. Verify one harmless public research task and reconcile provider usage against Qudron's ledger before expanding the task mix.
5. Treat any model/provider not covered by a supported protocol adapter as a discovery candidate only; do not silently enable it.
