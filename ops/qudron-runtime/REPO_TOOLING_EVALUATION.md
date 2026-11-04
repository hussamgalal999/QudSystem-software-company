# Qudron repository tooling review — 2026-11-04

This is a focused review of candidate repositories found in the connected GitHub account's 503-repository inventory. It is not a full code audit of all 503 repositories. License labels below were checked against the repository LICENSE file when available; re-check the exact commit and bundled dependencies before copying code into a commercial product.

## Recommended candidates

| Repository | Observed license | Best fit | Recommendation |
|---|---|---|---|
| agent-browser | Apache-2.0 | Browser control CLI for agents; native Rust CLI with Chrome install | First browser automation candidate. Run as a separate restricted worker, not inside the main API process. |
| browser-use | MIT | Python browser agent and web interaction | Alternative to agent-browser. Benchmark against it; avoid running two browser stacks initially. |
| mem0 | Apache-2.0 | Persistent memory layer for agents | Evaluate for scoped project memory only after defining retention, tenant isolation, export and deletion. Existing Qudron memory should not be replaced blindly. |
| RAG-Anything | MIT | Multimodal RAG over documents, tables, figures and images | Strong candidate for image/PDF/repository-document indexing; test on synthetic files and measure storage/compute. |
| LocalAI | MIT | Local OpenAI-compatible inference server | Useful gateway for small quantized models. The user's 10 GB desktop is not suitable for large frontier models; keep cloud API fallback. |
| OmniRoute | MIT | Multi-provider model gateway and fallback | Candidate for provider routing and health checks. Its README advertises many providers/free tiers; verify each provider's terms, limits and actual model IDs before use. |
| SWE-agent | MIT | Sandboxed repository issue resolution and coding tasks | Good separate coding worker for selected repositories; requires an isolated container, patch review and test gates. |

## Use with caution or avoid embedding

- agenticSeek — repository advertises GPL-3.0. Do not copy/merge its code into a proprietary QudSystem service without a deliberate copyleft compliance review. It can still be evaluated as a separately deployed process if its terms and distribution model fit.
- Dify — repository license is a modified Apache 2.0 with additional restrictions, including a multi-tenant limitation unless authorized. Do not use as QudSystem's multi-tenant SaaS backend without a commercial-license/legal review.
- AutoGen — repository README points new users toward Microsoft's Agent Framework; evaluate the maintained successor rather than adding another orchestration runtime.
- Mimo-Autonomous-Agent-3.5 — the connected repository's README is an AI Studio starter banner and no LICENSE file was found. Treat it as an unverified experiment; do not merge its code into production.

## Integration sequence

1. Browser: choose agent-browser OR browser-use after a benchmark of one synthetic login-free public workflow. Require domain allowlists, no saved user cookies by default, read-only mode first, and approval for any form submission or publication.
2. Images/documents: benchmark RAG-Anything against the current vision adapter using synthetic screenshots, UI references, PDF pages and diagrams. Keep extraction and OCR outputs traceable to source page/image coordinates.
3. Memory: compare mem0 with the existing SQLite memory store on retrieval quality, retention, redaction and tenant boundaries. Do not keep duplicate long-term copies of CVs or credentials.
4. Models: use OmniRoute only if it preserves Qudron's hard budget reservation, per-provider accounting and allowlist. Provider free tiers are not a substitute for stable production capacity.
5. Coding: run SWE-agent in an isolated workspace with branch-only write access and require CI plus human merge approval for main.

## Non-negotiable controls

- No arbitrary repository execution during inventory. Metadata/tree scan first; source file reads are bounded and prioritized.
- No model may write to main, change production secrets, send money, publish posts or message customers without a scoped permission gate.
- All browser sessions and customer data remain tenant-isolated. Do not use anonymous consumer ChatGPT pages or bypass login/access controls.
- Track every external call, provider, model, input/output token count, API fee, failure, retry and artifact hash.
- Never call an agent "fully autonomous" unless its host, credentials, persistence, budget, monitoring and recovery are actually configured and tested.
