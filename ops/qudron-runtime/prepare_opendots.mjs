import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();

function replaceOnce(path, before, after) {
  const file = join(root, path);
  const source = readFileSync(file, "utf8");
  const count = source.split(before).length - 1;
  if (count !== 1) {
    throw new Error(`Expected exactly one patch anchor in ${path}; found ${count}. Upstream changed; review before rebasing.`);
  }
  writeFileSync(file, source.replace(before, after));
}

replaceOnce(
  "src/server/platform-config.ts",
  "  ownerToken?: string;\n}",
  "  ownerToken?: string;\n  qudronMcpUrl?: string;\n  qudronMcpToken?: string;\n}",
);

replaceOnce(
  "src/server/connection-store.ts",
  "  saveTools(id: string, tools: ConnectionTool[], error: string | null = null) {",
  `  updateCredentials(id: string, value: { url: string; token?: string }) {
    this.db
      .prepare('UPDATE mcp_connections SET url=?, token=?, updatedAt=? WHERE id=?')
      .run(value.url, value.token || null, this.tick(id), id);
    return this.get(id);
  }
  saveTools(id: string, tools: ConnectionTool[], error: string | null = null) {`,
);

replaceOnce(
  "src/server/platform.ts",
  "  async start() {\n    this.setupTelemetry.start();",
  "  async start() {\n    this.setupTelemetry.start();\n    await this.ensureQudronDot();",
);

replaceOnce(
  "src/server/platform.ts",
  "  async stop() {",
  `  private async ensureQudronDot() {
    const url = this.config.qudronMcpUrl?.trim();
    const token = this.config.qudronMcpToken?.trim();
    if (!url || !token) return;

    const spaceName = 'Qudron Command Room';
    let space = this.workspace.spaces().find((item) => item.name === spaceName);
    if (!space)
      space = this.workspace.createSpace(
        spaceName,
        'The control room for Qudron: tasks, reports, model operations, and capability status.',
      );

    const dotName = 'Qudron Commander';
    let dot = this.workspace.dots().find((item) => item.name === dotName);
    if (!dot) {
      dot = this.workspace.createDot(
        space.id,
        dotName,
        [
          'You are the OpenDots control interface for Qudron, a separate autonomous execution platform.',
          'OpenDots is the conversation and control surface; Qudron is the system that executes tasks.',
          'Use the Qudron MCP connection as the source of truth for status, usage, queued work, and completed reports.',
          'For a task, submit only supported research, analysis, or draft jobs. Wait for the job status to become completed before saying it is done.',
          'Never claim that a queued job has been executed. Retrieve its result before summarizing it.',
          'The Qudron submit tool changes system state and requires owner approval. Do not bypass that approval.',
          'Do not claim publishing, payments, account changes, private customer-data processing, or shell access are available through this connection.',
          'Prefer the smallest useful task, idempotency keys, clear evidence, and explicit reporting of limitations.',
        ].join(' '),
        true,
        true,
        [space.id],
        null,
        false,
        false,
        [],
      );
    }

    const existing = this.workspace.connections.list(dot.id).find(
      (connection) => connection.name === 'Qudron',
    );
    if (existing) {
      this.workspace.connections.updateCredentials(existing.id, { url, token });
      const refreshed = await this.connections.refresh(existing.id);
      if (refreshed.error)
        throw new Error('Qudron MCP connection could not be refreshed; check the private service network and token.');
      return;
    }
    await this.connections.add(dot.id, { name: 'Qudron', url, token });
  }

  async stop() {`,
);

replaceOnce(
  "src/server/index.ts",
  "import { serveStatic } from '@hono/node-server/serve-static';",
  "import { serveStatic } from '@hono/node-server/serve-static';\nimport { readFileSync } from 'node:fs';",
);

replaceOnce(
  "src/server/index.ts",
  "const ownerToken = process.env.OWNER_TOKEN;",
  `const ownerToken = process.env.OWNER_TOKEN;
function secretFromEnv(name: string, fileName: string): string | undefined {
  const direct = process.env[name]?.trim();
  if (direct) return direct;
  const path = process.env[fileName]?.trim();
  if (!path) return undefined;
  try {
    return readFileSync(path, 'utf8').trim() || undefined;
  } catch {
    return undefined;
  }
}`,
);

replaceOnce(
  "src/server/index.ts",
  "  apiKey: process.env.OPENAI_API_KEY,",
  "  apiKey: secretFromEnv('OPENAI_API_KEY', 'OPENAI_API_KEY_FILE'),",
);
replaceOnce(
  "src/server/index.ts",
  "  browserSecret: process.env.BROWSER_SECRET,",
  "  browserSecret: secretFromEnv('BROWSER_SECRET', 'BROWSER_SECRET_FILE'),",
);
replaceOnce(
  "src/server/index.ts",
  "  voiceKey: process.env.VOICE_API_KEY,",
  "  voiceKey: secretFromEnv('VOICE_API_KEY', 'VOICE_API_KEY_FILE'),",
);
replaceOnce(
  "src/server/index.ts",
  "  ownerToken,\n};",
  "  ownerToken,\n  qudronMcpUrl: process.env.QUDRON_MCP_URL,\n  qudronMcpToken: secretFromEnv('QUDRON_MCP_TOKEN', 'QUDRON_MCP_TOKEN_FILE'),\n};",
);
console.log("Applied the pinned OpenDots↔Qudron integration patch.");
