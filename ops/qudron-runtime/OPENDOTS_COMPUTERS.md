# OpenDots per-Dot computers (optional)

This overlay adds the upstream OpenBot supervisor and browser/computer images to OpenDots. It is separate from the core OpenDots↔Qudron MCP control connection.

## Security boundary

- Only `computer-supervisor` receives the Docker Engine socket. The OpenDots app and each Dot computer do **not** receive the host socket.
- The supervisor API is reachable only over an internal Compose network; it has no published host port.
- Each Dot receives its own computer/workspace/browser profile through the upstream supervisor. The computer image and supervisor source are pinned to reviewed OpenBot commit `b6932d31a8d6e7896c15139dfc27a6c6911deb27`.
- Standard Docker containers share the host kernel. They are not VM-grade isolation. Use a dedicated host for untrusted browsing and configure gVisor (`COMPUTER_RUNTIME=runsc`) only when the host has it installed and tested.
- Docker socket access is equivalent to high privilege on the host. Do not enable this overlay on a shared or sensitive host unless you accept that trust boundary.

## Prepare and start

From `ops/qudron-runtime`:

```sh
python3 scripts/prepare_opendots_computers.py .env
docker compose -f docker-compose.yml -f docker-compose.opendots.yml -f docker-compose.opendots-computers.yml --profile opendots --profile build-computers build computer-image
docker compose -f docker-compose.yml -f docker-compose.opendots.yml -f docker-compose.opendots-computers.yml --profile opendots --profile opendots-computers up -d --build qudron freellm opendots opendots-bootstrap computer-supervisor
```

The preparation script generates 48-byte random supervisor/client tokens only when the .env values are blank, preserves existing tokens, writes atomically, and sets file mode 0600. It never prints token values.

## Capacity and resource controls

- Each running Dot computer can consume up to `COMPUTER_MEMORY_BYTES` (default 2 GiB). The browser mode defaults to headless.
- The supervisor creates and removes per-Dot containers and persistent volumes. It does not create 10,000 live desktops; scale computer capacity separately from agent/task concurrency.
- For a small 10 GB desktop, start with one computer and monitor RAM/CPU before increasing concurrent browser sessions. A dedicated cloud VM is better for persistent multi-user use.
- Set `COMPUTER_NAMESPACE` to a unique namespace if sharing one Docker host with another OpenDots deployment.
- Set `ENGINE_SOCKET` only to the trusted Docker socket path and `COMPUTER_RUNTIME` only to a runtime installed on the host.

Qudron's own background queue and workers remain independent of the OpenDots computer pool. When OpenDots closes, queued Qudron jobs continue on the host as long as Qudron remains running.
