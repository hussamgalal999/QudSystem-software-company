# Manus API v2 integration

## Status

An official REST API v2 adapter now exists in manus_adapter.py. It is opt-in, contract-tested with mocks, and persists external task references through ContinuityStore. It has **not** been connected to a live Manus account or tested against a live task.

## Supported operations

- Create an asynchronous task with a private share visibility.
- Poll task.listMessages and retain the most recent status event and event ID.
- Inspect task.detail, including whether background jobs remain active after the main agent stops.
- Send a follow-up message to continue a task.

The adapter is based on the official Manus v2 documentation:
- https://open.manus.ai/docs/v2/introduction
- https://open.manus.ai/docs/v2/task.create
- https://open.manus.ai/docs/v2/task.listMessages
- https://open.manus.ai/docs/v2/task.detail
- https://open.manus.ai/docs/v2/task.sendMessage
- https://open.manus.im/docs/v2/task-lifecycle

## Access and cost policy

Manus API v2 requires an API key or OAuth bearer token with the appropriate scope. This adapter does not scrape browser cookies or reuse private web sessions. The existence of an API endpoint does not mean the user's account has free API credits. The API reports credit usage; free personal accounts may be downgraded to the lite profile. Qudron must not enable this adapter as an inference source until the owner verifies permitted access, account entitlement, quota and credit policy.

## Environment variables

Set these only in a private host secret manager after verification:

- QUDRON_MANUS_ENABLED=true
- QUDRON_MANUS_CREDENTIAL_TYPE=api_key or oauth
- MANUS_API_KEY or MANUS_ACCESS_TOKEN
- QUDRON_MANUS_TIMEOUT_SECONDS
- QUDRON_MANUS_RETRIES

The default is disabled. Do not put secrets in Git, reports, prompts or ChatGPT.

## Important lifecycle details

task.listMessages returns a messages[] collection; poll status_update events. A task with status stopped is not necessarily completely finished: task.detail may report has_running_background_jobs=true. Keep monitoring when background work remains.

**Owner-confirmation limitation:** Manus event inspection and `confirm_input_schema` handling are not implemented as an automatic Qudron workflow. The adapter now fails closed: `task.sendMessage` requires a scoped, one-time owner approval token for that exact task. The generic AgentFabric follow-up path does not yet supply this token, so it remains blocked until an authenticated owner-facing approval flow is connected. Qudron must never auto-confirm unrecognized actions.
