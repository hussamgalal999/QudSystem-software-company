# Qudron Windows execution node

The Windows node delegates bounded desktop work to the owner's Windows computer. It uses Microsoft's UI Automation model through the optional Python package pywinauto.

## Why it is a user-session process

Windows UI automation requires an interactive desktop. Do not install this process as a generic Session-0 Windows service and assume it can control the user's visible desktop. Start it in the signed-in user's session, for example through Task Scheduler using the At log on trigger. This is separate from a service that monitors health or launches the user-session worker.

Microsoft UI Automation exposes a tree of windows and controls that can be inspected or invoked. Power Automate Desktop is another Windows automation surface and may be connected as a separate adapter; its unattended run capacity and licensing are independent and must be measured rather than assumed.

## Supported operations

- windows.list_windows — read visible window titles and process identifiers.
- windows.inspect_window — inspect a bounded UI Automation tree for one process.
- windows.launch_app — launch one alias from the explicit owner allowlist.
- windows.invoke_control — invoke one identified control inside an exact window title and process ID.
- windows.type_text — type one bounded text value into one identified Edit control inside an exact window title and process ID.

There is no arbitrary shell, PowerShell, file-system traversal, process injection, credential dumping or remote desktop takeover endpoint.

## Approval and conflict prevention

Read-only inspection requires the owner node token. Launch/click/type operations also require a short-lived HMAC-signed approval envelope that binds the approver, action, process ID, exact window title, automation ID, control type, expiry and one-time nonce. Changing the target window invalidates the approval. The node rejects altered payloads, expired approvals and replayed nonces. The task idempotency key prevents a retried network request from repeating an already completed UI action.

Keep each desktop workflow scoped to a named application and target control. UIA identifiers can change across app versions; verify the target immediately before acting. Do not run two writers against the same application/document concurrently. Use Qudron resource claims to serialize those tasks.

## Setup on the owner's Windows device

1. Install Python 3.11+ and the optional pywinauto dependency in a dedicated virtual environment.
2. Create strong private values for QUDRON_WINDOWS_NODE_TOKEN and QUDRON_WINDOWS_APPROVAL_SECRET in the Windows user's secret store/environment. Do not add them to Git or chat.
3. Set QUDRON_WINDOWS_ALLOWED_APPS_JSON to a small JSON object of permitted app aliases and absolute executable paths, for example an alias for Notepad or an approved browser profile.
4. Start python -m windows_node.worker in the signed-in user's desktop session.
5. Verify GET http://127.0.0.1:8787/health.
6. Connect Qudron through a private SSH tunnel or local bridge. Do not bind this node to 0.0.0.0 or expose it directly to the internet.

The worker stores only safe task-receipt metadata locally. UI text, typed text, and full UIA trees are not persisted by default. A separate application may still store its own data; its retention policy remains applicable.

## References

- Microsoft UI Automation client overview: https://learn.microsoft.com/en-us/windows/desktop/WinAuto/uiauto-clientsoverview
- Microsoft UI Automation specification: https://learn.microsoft.com/en-us/windows/win32/winauto/ui-automation-specification
- Power Automate desktop automation: https://learn.microsoft.com/en-us/power-automate/desktop-flows/desktop-automation
- Power Automate machine management: https://learn.microsoft.com/en-us/power-automate/desktop-flows/manage-machines
