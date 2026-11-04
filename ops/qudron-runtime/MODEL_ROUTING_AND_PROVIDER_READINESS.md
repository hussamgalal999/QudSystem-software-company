# Qudron model routing and provider readiness

As of 2026-11-04, Qudron's runtime can route each specialist to one of three configured profiles: FAST, BALANCED, REASONING. Each profile accepts its own base URL, API key, model ID and input/output token prices. This is an endpoint router, not an automatic universal entitlement to every commercial model.

## Current candidate routing
1. FAST: DeepSeek V4.1 Flash 1017 (deepseek-flash) — image-capable and tool-capable. Use peak rates for conservative budgeting: $0.30/M input and $1.20/M output. DeepSeek has separate off-peak and cache-hit pricing; live prices must be rechecked before launch.
2. BALANCED: Xiaomi MiMo V2.6 Flash ($0.14/M input, $0.28/M output) or Pro ($0.435/M input, $0.87/M output). Official base URL is https://api.xiaomimimo.com/v1. Pro accepts text, images, video and audio and has a 1M context.
3. REASONING: Meta Muse Wonder through OpenRouter ($4/M input, $20/M output) for high-stakes complex tasks; Muse Spark Open ($1.25/M input, $4.25/M output) is the cheaper coding/agentic alternative. Both are hosted API calls, not models that can run on the user's 10 GB local machine.

All prices are snapshots and provider prices may change. The model catalog records source URLs, modalities, context limits and conservative cost rates. It does not activate any provider.

## Optional .env profile examples
Uncomment only after creating keys directly in the provider dashboards and setting daily/monthly hard spend caps:

DeepSeek FAST:
- LLM_FAST_BASE_URL=https://api.deepseek.com
- LLM_FAST_MODEL=deepseek-flash
- LLM_FAST_API_KEY=<DEEPSEEK_API_KEY>
- LLM_FAST_INPUT_USD_PER_1M=0.30
- LLM_FAST_OUTPUT_USD_PER_1M=1.20

Xiaomi MiMo BALANCED:
- LLM_BALANCED_BASE_URL=https://api.xiaomimimo.com/v1
- LLM_BALANCED_MODEL=mimo-v2.6-pro
- LLM_BALANCED_API_KEY=<MIMO_API_KEY>
- LLM_BALANCED_INPUT_USD_PER_1M=0.435
- LLM_BALANCED_OUTPUT_USD_PER_1M=0.87

Meta Muse Wonder REASONING through OpenRouter:
- LLM_REASONING_BASE_URL=https://openrouter.ai/api/v1
- LLM_REASONING_MODEL=meta/muse-wonder
- LLM_REASONING_API_KEY=<OPENROUTER_API_KEY>
- LLM_REASONING_INPUT_USD_PER_1M=4.00
- LLM_REASONING_OUTPUT_USD_PER_1M=20.00

For a lower-cost multimodal reasoning profile, use meta/muse-spark-open at $1.25/M input and $4.25/M output. The runtime's conservative budget estimator does not account for provider-specific cache discounts, search-call fees, audio/video duration billing, or variable peak/off-peak schedules; provider-side hard caps remain mandatory.

## Activation sequence
- Store keys only in the deployment platform's secret manager, never in GitHub source or ChatGPT.
- Set a small positive daily/monthly USD cap and exact rates for every active profile. Keep QUDRON_REQUIRE_MODEL_BUDGET=true.
- Run one harmless synthetic prompt per profile and one image test with synthetic data.
- Confirm provider usage and billed cost in the provider console; reconcile it against Qudron's local ledger.
- Only then route real project tasks. Keep customer CVs and personal data off anonymous/free endpoints.

## Web and tool access
The model endpoint alone does not give Qudron browser access, unrestricted internet access, repository write permissions, or the ability to use tools. Each tool must be separately implemented, authenticated, permission-scoped, logged and tested. Qudron must not scrape consumer ChatGPT pages or reuse browser sessions/cookies to bypass login or access controls.
