# Artemis physical-device E2E runbook

This test exercises the complete path **Qudron MCP Gateway → authenticated host bridge → upstream Artemis MCP → Android device**. It does not call the host bridge directly.

## Preconditions

1. Artemis is installed independently on the Android host and checked out at the commit pinned in `artemis_bridge_config.example.json`.
2. The Artemis host bridge is running with a strong `ARTEMIS_BRIDGE_TOKEN`.
3. Qudron is running with `ARTEMIS_BRIDGE_URL` and the matching `ARTEMIS_BRIDGE_TOKEN` configured in its private environment.
4. The Android owner has explicitly authorized USB debugging and the target serial is known.
5. The test operator has the Qudron API token (or readable `QUDRON_API_TOKEN_FILE`) for the Qudron MCP endpoint.
6. Android Platform Tools (`adb`) are installed on the test host.

## Run

From the Qudron runtime directory, preferably inside the same runtime container/network that can reach the configured bridge:

```bash
QUDRON_ARTEMIS_E2E=1 \
ARTEMIS_DEVICE_SERIAL="<authorized-device-serial>" \
QUDRON_MCP_URL="http://127.0.0.1:8765/mcp" \
QUDRON_API_TOKEN_FILE="/run/qudron-auth/api_token" \
python -m unittest tests.test_artemis_android_e2e -v
```

If running outside the container, set `QUDRON_API_TOKEN` and a reachable `QUDRON_MCP_URL` instead of relying on the container token-file path.

The test initializes the Qudron MCP endpoint, starts `qudron_android_run_task` with the Pro profile and strict verification, polls `qudron_android_task_status`, then inspects the trace through `qudron_android_inspect_trace`. It requires a terminal completed state, a battery percentage associated with battery context in the result/trace, and an exact match against the read-only ADB reference from `adb -s <serial> shell dumpsys battery`.

## Interpretation

- A skipped test means the explicit opt-in flag was not set; it is not a pass.
- A passing unit/contract test does not prove physical Android connectivity.
- A passing physical E2E test is evidence for the specific device, Artemis checkout, Qudron runtime and app/OS state used in that run only.
- Do not run against a device unless its owner authorized USB debugging and the operation. This test is read-only: it must not change settings.
