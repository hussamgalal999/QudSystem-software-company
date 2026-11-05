# Qudron × Google ARTEMIS Integration

**Status:** implementation branch; host bridge and Qudron MCP tools are drafted. Physical-device E2E and deployment are pending.
**Upstream:** [google/artemis](https://github.com/google/artemis) (Apache-2.0)
**Integration rule:** Artemis is a specialist Android device capability. Qudron remains the executive orchestrator.

## 1. Architectural analysis

The upstream README and MCP documentation describe ARTEMIS as a real-device Android automation system with a native MCP server, CLI, web console and remote Python SDK.

### Core capability extracted

The core capability is a closed-loop mobile operator:

1. Observe the current Android screen through accessibility/UI hierarchy, OCR and screenshot perception.
2. Ground UI targets using element identifiers first, then OCR/visual coordinates as fallback.
3. Execute interactions on a real Android device.
4. Retain trace/history and report task state.
5. Diagnose the host/device environment and collect execution evidence.

Qudron does not copy ARTEMIS internals. It invokes the upstream MCP tools through a host-side adapter.

### MCP tool surface

The upstream mcp_server/README.md documents these tools:

| Upstream tool | Qudron use |
|---|---|
| mobile_run_task | Start an Android workflow asynchronously |
| mobile_manage_task | Poll, stop or steer a running task |
| mobile_get_device_state | Read screenshot or UI hierarchy |
| mobile_inspect_trace | Inspect summary, steps, history and screenshots |
| mobile_diagnose | Read readiness and device diagnostics |

### Python SDK

packages/artemis-client is a zero-runtime-dependency remote HTTP client. It talks to the Artemis daemon API (/api/run, /api/sessions/{id}, /api/status, /api/stop, /api/devices, /api/system/readiness). It does not contain ADB, device drivers, agent or LLM code.

The SDK is useful for a future HTTP-only control plane, but this integration uses the upstream MCP server as the primary bridge, as requested.

### Flash versus Pro

- **Flash:** reactive Observe–Think–Act loop, normally faster and more token-efficient. Best for predictable, low-risk navigation and short UI operations. It does not provide the Pro planning/checkpoint verification/safety-net/reporting workflow.
- **Pro:** multi-agent plan/execute/verify flow with a living plan, per-action safety checks (with documented fast-action bursts), execution-incident recovery, read-only Checker, optional report, and ADB/log/video diagnostics. Use for exploratory, branching, diagnostic or high-assurance workflows.
- Qudron selects the profile from task complexity and risk. It must not claim that Flash has Pro's verification guarantees.

### ADB and scrcpy

- **ADB** is the device transport and diagnostic toolchain used by Artemis to discover/authorize devices, install its accessibility helper, collect diagnostics and support Pro-level shell/log operations.
- **scrcpy** supports screen mirroring/recording and video-analysis workflows. It is not the orchestration authority.
- The Artemis helper exposes accessibility hierarchy data locally on the phone. Artemis documents fallback to UIAutomator2 if the helper is unavailable.
- ADB USB authorization is a user-controlled trust decision. The owner must approve the Android debugging prompt on the phone.

Upstream claims AndroidWorld benchmark performance in its README; Qudron does not treat that upstream claim as a guarantee for the user's device or applications.

## 2. Integration architecture

~~~mermaid
flowchart LR
  A[Qudron Planner / Operator] --> B[Qudron MCP Gateway]
  B -->|Private HTTP + bearer token| C[Qudron Artemis Bridge]
  C -->|MCP stdio JSON-RPC| D[Upstream ARTEMIS MCP Server]
  D --> E[ARTEMIS Agent Runtime]
  E --> F[ADB / UIAutomator2 / Accessibility]
  F --> G[Physical Android phone or emulator]
  G --> F
  F --> E
  E --> D
  D --> C
  C --> B
  B --> A
~~~

### Separation of responsibilities

- **Qudron:** goal decomposition, approvals, budget, agent assignment, cross-project memory, policy and final reporting.
- **Bridge:** authentication, strict tool allowlist, request validation, bounded result serialization and MCP process lifecycle.
- **Artemis:** Android-specific perception, planning/execution profile, device locks, traces, diagnostics and recovery.
- **Android device:** executes only after USB debugging/device authorization has been explicitly enabled by its owner.

### Qudron tool names

| Qudron MCP tool | Upstream mapping | Approval |
|---|---|---|
| qudron_android_run_task | mobile_run_task | Ask first |
| qudron_android_task_status | mobile_manage_task(action=status) | Read-only |
| qudron_android_task_control | mobile_manage_task(action=stop/inject_instruction) | Ask first |
| qudron_android_get_device_state | mobile_get_device_state | Read-only |
| qudron_android_inspect_trace | mobile_inspect_trace | Read-only |
| qudron_android_diagnose | mobile_diagnose with repair/probe flags forced off | Read-only |

The bridge does not expose arbitrary shell commands. mobile_diagnose is restricted to read-only diagnostics; automatic fixes, emulator launch, live credential verification and device smoke probes are not exposed by this initial adapter.

## 3. Data flow

1. Qudron sends a named tool call and validated arguments to the bridge.
2. The bridge authenticates the bearer token and rejects tools outside its allowlist.
3. The bridge launches the configured Artemis MCP server as a local stdio subprocess.
4. It initializes an MCP ClientSession, invokes the requested upstream tool, and serializes text/structured/image content.
5. Artemis mobile_run_task returns a trace identifier while the actual device workflow continues in Artemis' background runner.
6. Qudron polls through qudron_android_task_status and obtains trace evidence through qudron_android_inspect_trace.
7. Qudron records the trace ID, selected device, profile, status, verification evidence and result in its project memory.

The bridge converts only bounded screenshot files under the Artemis checkout/traces directory to MCP image blocks. Arbitrary host paths are never read or returned as file contents.

## 4. Installation and operation

### A. Prepare the Android host

Use a computer that has the physical Android device connected (or a supported emulator). Install the upstream project according to its own instructions:

~~~bash
git clone https://github.com/google/artemis.git
cd artemis
git checkout 351ca8422f7b5b54e80a9c1ce03a222e02415b6b
./start.sh
~~~

On Windows, use start.bat as documented upstream. Complete Android USB debugging authorization on the phone. Do not accept an unknown computer's ADB key.

Check the upstream environment before connecting Qudron:

~~~bash
uv run artemis doctor
adb devices -l
~~~

### B. Install the Qudron bridge into the Artemis Python environment

The bridge file is maintained in Qudron, not copied into the Artemis repository. Place/access ops/qudron-runtime/artemis_bridge.py on the Android host and run it using the Artemis virtual environment, where the upstream mcp, FastAPI and Uvicorn dependencies are installed.

Example environment (Linux/macOS):

~~~bash
cp /path/to/QudSystem-software-company/ops/qudron-runtime/artemis_bridge_config.example.json /path/to/artemis_bridge_config.json
# Edit mcp.command, mcp.cwd, and bind_host in the copied JSON file.
export ARTEMIS_BRIDGE_CONFIG="/path/to/artemis_bridge_config.json"
# Optional environment overrides: ARTEMIS_MCP_COMMAND, ARTEMIS_MCP_ARGS_JSON,
# ARTEMIS_MCP_CWD, ARTEMIS_EXPECTED_COMMIT, ARTEMIS_BRIDGE_BIND_HOST, ARTEMIS_BRIDGE_PORT.
export ARTEMIS_BRIDGE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ARTEMIS_BRIDGE_BIND_HOST="0.0.0.0"
export ARTEMIS_BRIDGE_PORT="8766"
python /path/to/QudSystem-software-company/ops/qudron-runtime/artemis_bridge.py
~~~

Keep the token in the host secret manager or a permission-restricted environment file. Do not commit it or paste it into chat.

### C. Connect the Qudron runtime

Set these variables in the private Qudron .env:

~~~dotenv
ARTEMIS_BRIDGE_URL=http://host.docker.internal:8766
ARTEMIS_BRIDGE_TOKEN=<same-host-generated-secret>
ARTEMIS_BRIDGE_TIMEOUT_SECONDS=120
~~~

The Qudron Docker Compose service adds the host.docker.internal:host-gateway mapping. If your platform does not support this alias, configure a private reachable address instead.

Restrict inbound port 8766 at the host firewall to the Qudron Docker network or private VPN. Do not expose this bridge or the upstream Artemis daemon directly to the public internet. Use TLS at a private reverse proxy if traffic crosses an untrusted network.

### D. Verify

- GET /health checks bridge process liveness only; it does not prove Artemis or a phone is ready.
- Use qudron_android_diagnose for read-only host/device readiness.
- Use qudron_android_get_device_state(view_type=hierarchy) to inspect the current screen.
- Start with a harmless, explicitly approved test task.
- Store the returned trace ID in Qudron memory and poll until Artemis reports a terminal state.
- Inspect the trace and confirm the requested state rather than relying only on a natural-language success claim.

## 5. Test plan

### Automated contract tests

tests/test_artemis_mcp_integration.py tests Qudron's tool registration, native tool mapping, read-only versus approval-gated annotations, and fail-closed argument validation without requiring a phone.

### Physical-device end-to-end test

tests/test_artemis_android_e2e.py is an opt-in test. It submits the task:

> Open Android System Settings, navigate to Battery, read the displayed battery percentage, and report the exact percentage. Do not change any setting.

Run it only after the bridge is deployed, the phone is authorized, and the owner has approved the operation:

~~~bash
ARTEMIS_DEVICE_SERIAL="<authorized-device-serial>" QUDRON_ARTEMIS_E2E=1 python -m unittest tests.test_artemis_android_e2e -v
~~~

This repository change does not claim that a physical-device run has passed. The test must be run on the actual Android host and its returned trace must be reviewed.

For the exact host-side command, token handling, and ADB cross-check for the physical-device test, see [ARTEMIS_E2E_RUNBOOK.md](./ARTEMIS_E2E_RUNBOOK.md).

## 6. Limitations and risks

- The Android host must remain online and have an authorized device attached.
- ADB authorization and Artemis' accessibility helper require explicit device-owner consent.
- Only one Artemis task may operate a given device at a time; separate devices can run independently.
- Flash is fast but does not provide Pro's checkpoint verification. Use Pro for higher-risk tasks.
- Artemis model/API credentials remain configured on the Artemis host; Qudron does not receive or relay those secrets.
- The MCP bridge token protects the bridge but does not replace a private network, firewall or TLS.
- Screenshot artifacts are bounded and only read from known Artemis locations.
- UI automation can make real changes. Qudron must require approval for task execution and stop/inject controls; do not use it for payments, financial transfers, account security changes or irreversible actions without a separate explicit authorization and workflow.
- Upstream tool names and schemas may change. Pin and test an Artemis commit/release before production upgrades.
- This integration does not clone or vendor Artemis. Install and update the upstream project independently under its Apache-2.0 license.

## 7. Upstream references

- [ARTEMIS repository and README](https://github.com/google/artemis)
- [ARTEMIS MCP server documentation](https://github.com/google/artemis/blob/main/mcp_server/README.md)
- [ARTEMIS MCP agent rules](https://github.com/google/artemis/blob/main/mcp_server/rules.md)
- [ARTEMIS remote Python SDK](https://github.com/google/artemis/tree/main/packages/artemis-client)
- [ARTEMIS configuration](https://github.com/google/artemis/blob/main/config/artemis.jsonc)
