# Qudron AI Provider Strategy (2026-11-04)

## Objective

Give Qudron one OpenAI-compatible model interface with provider discovery, quota-aware routing, health checks, retries, circuit breakers, spend limits, and an auditable fallback chain. Prefer legitimate free tiers and open-weight inference. Never depend on scraped browser cookies, copied session tokens, shared accounts, or undocumented private endpoints.

## Candidate projects reviewed

| Project | Role | Why it is relevant | Main caveat |
|---|---|---|---|
| [OmniRoute](https://github.com/diegosouzapw/OmniRoute) | Candidate primary gateway | Unified API, broad provider catalog, quota-aware fallback, OAuth support for some providers, dashboard and observability | Large, fast-moving project; review license, provider adapters, security model and resource footprint before adopting. Some web/session adapters are fragile and must not be used for production customer data. |
| [FreeLLM 0.5.2](https://github.com/shihabshahrier/freelm) | **Integrated optional sidecar** | OpenAI-compatible `/v1` endpoint, free-tier discovery, quota-aware routing, retries and keyless Kilo/OVH fallbacks | Anonymous endpoints have low limits and may log prompts. Enabled only by Compose profile `free-ai`; never send CV/customer PII to them. |
| [LiteLLM](https://github.com/BerriAI/litellm) | Production-grade gateway alternative | Broad provider compatibility, routing, retries/fallbacks, virtual keys and cost tracking | Does not create free quota; provider credentials and prices still need configuring. |
| [Inference Gateway](https://github.com/inference-gateway/inference-gateway) | Alternative self-hosted gateway | OpenAI-compatible multi-provider gateway, MCP/A2A and local Ollama/llama.cpp support | More infrastructure/configuration than a small first pilot. |
| [Ollama](https://github.com/ollama/ollama) / [llama.cpp](https://github.com/ggml-org/llama.cpp) | Local inference | No remote API key after model download; useful for private classification, extraction, drafting and fallback | Compute and RAM/VRAM are paid by the hardware owner. Large frontier models are not practical on Qudron's currently documented modest RAM machines. |

## Model availability notes

- **Xiaomi MiMo-V2.6-Pro / Flash**: Xiaomi has open-sourced model weights and research assets. The Flash model is still a 309B-total / 15B-active MoE; published vLLM recipes call for accelerator systems with at least ~208 GB aggregate VRAM for the documented deployment. Do not plan to run the full model on a 10–16 GB RAM desktop. Prefer an official hosted endpoint when available, or a smaller distilled/quantized derivative after license and quality checks.
- **Meta Muse**: Meta's current Muse family includes Muse Wonder and Muse Spark 1.3. Do not assume Muse weights are open or that a public API/free quota exists. Integrate only through an official API or user-authorized official product workflow if offered; otherwise mark unavailable.
- **DeepSeek**: official release notes identify DeepSeek-V4.1-Flash as the September 2026 API model. Verify current endpoint/model identifiers and pricing against the official account before enabling. Do not hard-code stale model names.
- Model catalogs and free quotas change frequently. Run a daily/weekly capability probe and disable retired, unavailable, paid-only, or tool-incompatible models automatically.

## Recommended routing policy

1. **Tier 0 — local/private**: small Ollama/llama.cpp models for redaction, language detection, routing, simple extraction and low-risk summaries.
2. **Tier 1 — legitimate free tiers**: FreeLLM adapter or direct official connectors for Google AI Studio, Groq, OpenRouter :free, Cloudflare Workers AI, Mistral free/experiment, NVIDIA NIM trial, and other currently verified free plans. Store each user's own credentials encrypted; never pool unrelated users' accounts.
3. **Tier 2 — authorized OAuth**: providers whose official CLI/OAuth flow explicitly permits this use. User initiates consent; tokens are encrypted, scoped, revocable and refreshed only through documented flows. Do not extract Antigravity, Google AI Studio, Meta AI, or other browser cookies/local storage. Do not use ChatGPT Web/Codex browser sessions as a hidden API.
4. **Tier 3 — paid fallback**: DeepSeek or another low-cost provider, only when a per-task and daily/monthly budget is configured and an owner has enabled billing.
5. **Tier 4 — no provider**: queue the job, return a clear NEEDS_PROVIDER state, and preserve its idempotency key. Never silently switch to a paid model or silently drop the task.

## Routing and safety requirements

- Maintain a provider registry: provider, model ID, modality, context window, tool-call support, free/paid status, current quota, region, last successful probe, latency, error rate and data-retention classification.
- Route by task class and capability, not just model name. CVPen requires reliable structured output and document-fact checking; generic anonymous web endpoints are not eligible.
- Use exponential backoff with jitter, per-provider circuit breakers, concurrency limits, idempotency and bounded retries.
- Enforce hard per-order, daily and monthly cost ceilings before dispatch. Reserve budget atomically across parallel agents. Paid routes are disabled unless prices and budget are explicitly configured.
- Never rotate keys to evade a provider's published limits or terms. Key rotation is only for separately authorized keys within the provider's allowed usage.
- Never send CVs, contact details, payment evidence, secrets or other customer PII to anonymous endpoints. Use redaction and tenant-scoped encrypted storage.
- Log provider/model, request ID, latency, token usage, cost, fallback reason and final status; never log credentials or raw sensitive prompts.
- Add provider contract tests for tool calls, JSON mode, streaming, timeout, 429, 5xx, malformed output, model retirement and budget exhaustion.

## Proposed integration sequence

### Phase A — safe internal pilot
- Keep the existing Qudron runtime and queue as the control plane.
- Add a provider adapter interface (list_models, health, chat, usage, capabilities).
- Integrate FreeLLM as an optional free-only adapter behind a feature flag; run doctor and contract tests on the host before enabling.
- Keep LiteLLM as the conservative fallback gateway for explicitly configured providers.
- Add local Ollama only for small models and privacy-sensitive low-compute tasks.
- Do not deploy OmniRoute until a code/license/security review and a measured resource test are complete.

### Phase B — broader provider coverage
- Evaluate OmniRoute in an isolated staging environment. Disable browser-cookie/session-based adapters by default. Enable only official API-key or documented OAuth providers with user consent.
- Test Gemini/Antigravity OAuth only through documented provider login and token lifecycle. If the provider terms do not authorize headless gateway use, keep it out.
- Add model catalog sync and periodic health/quota probes.
- Add provider-specific adapters only after verifying exact current model IDs, terms, region availability and pricing.

### Phase C — CVPen production gate
- Only use providers approved for customer data and commercial use.
- Require signed PSP payment evidence separately; model provider success is not payment evidence.
- Run tenant isolation, PII redaction, retention/deletion, prompt-injection, output validation and cost-cap tests.
- Start with a small internal cohort. Do not enable public customer intake or paid fulfillment until end-to-end tests pass.

## Current implementation status

- FreeLLM 0.5.2 sidecar code is integrated on the release-candidate branch; it is optional and not running in production. Quota/cooldown state is persisted in a named Docker volume across sidecar restarts.
- GitHub Actions run #82 passed on commit `29749aa503f8b5bf6c18f555c1a3032705704e54`: 64 tests, Qudron and FreeLLM Docker builds, Compose profile validation, sidecar health/bearer-auth smoke test, and Cairo timezone check. Run #79 also passed on the earlier documentation-updated commit.
- No provider API keys, OAuth sessions, or customer credentials have been installed. The CI test validates sidecar startup/authentication, not successful live inference from each upstream provider.
- OmniRoute remains an evaluated candidate, not yet integrated. Its current README advertises 231 providers, 50+ free tiers and OAuth/web-cookie routes; those are upstream claims and each route still needs provider-terms, privacy and security review. The repository is MIT licensed, but some OAuth/web-cookie/CLI subscription integrations may be subject to separate upstream provider terms. Never enable web-cookie adapters for customer data or bypass a provider's terms.
- Qudron is still not merged or deployed. The release candidate still needs a host, owner-approved provider configuration, exact prices/budgets and an approved release.


## Zero-key inference option for the Cloudflare edge runtime (4 November 2026)

**Preferred no-separate-model-key option:** Cloudflare Workers AI through the native Worker AI binding (`env.AI.run()`). The binding can invoke Workers AI models directly without a separate model-provider API key. This is only available inside a deployed Cloudflare Worker; it does not make the existing Python/Docker container keyless by itself.

- Workers AI Free currently includes 10,000 Neurons per day at no charge. On the Free plan, exceeding the free allowance causes requests to fail; moving beyond it requires the Workers Paid plan, which starts at $5/month and charges overage. Do not enable the Paid plan without explicit approval.
- A documented Free-plan candidate is `@cf/zai-org/glm-4.7-flash`. The current pricing page lists 5,500 Neurons per million input tokens and 36,400 Neurons per million output tokens; the daily allowance is finite and shared across use, not an unlimited free model.
- Other models may be blocked behind paid billing. The current official changelog identifies Kimi K2.6, Kimi K2.7 Code and GLM 5.2 as requiring Workers Paid. Re-check model eligibility before changing the model ID.
- Cloudflare's Workers AI data-usage documentation (updated 16 October 2026) states that standard inference content is processed only as needed, is not retained after processing absent stateful storage features, and is not used to train AI models. If prompts or reports are written to R2/D1/logs, those storage systems have their own retention configuration. Review each model's third-party license.
- This route is the best initial candidate for internal non-sensitive Qudron tasks where a Cloudflare Worker is the execution runtime. It is not yet integrated or deployed. Existing Docker Qudron still needs a configured provider adapter or API endpoint.

Official references:
- Workers AI pricing and Neuron allowance: https://developers.cloudflare.com/workers-ai/platform/pricing/
- Direct AI binding: https://developers.cloudflare.com/workers-ai/configuration/bindings/
- Free-plan model eligibility changelog: https://developers.cloudflare.com/changelog/post/2026-07-28-models-require-workers-paid/
- Workers AI data usage/privacy: https://developers.cloudflare.com/workers-ai/platform/data-usage/

## Other currently free provider routes and privacy cautions

- **Gemini API Free:** Google documents free input/output token access for selected models, but explicitly labels free-tier content as used to improve its products. Keep it to public/non-sensitive prompts; do not send CVs, customer records, IDs, payment evidence, secrets or confidential business material on that tier. Exact quotas are visible per project in AI Studio and are not guaranteed.
- **Groq Free:** a usable API-key route with model-specific request/token limits. The current exact limits vary by organization and model, are visible in the account console, and requests may return HTTP 429. It is not unlimited capacity.
- **Cerebras Free:** an official free API tier is listed, but the public pricing page is old and its free-tier rate limits are described only as lower limits. Treat it as an experimental fallback until a current account quota is checked.

Never use a free route as a reason to send confidential customer data to an endpoint without checking provider-specific terms.