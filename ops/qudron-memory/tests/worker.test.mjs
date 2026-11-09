import test from "node:test";
import assert from "node:assert/strict";

import memoryWorker from "../src/index.ts";

const env = (overrides = {}) => ({
  QUDRON_MEMORY_TOKEN: "test-memory-token",
  MAX_BODY_BYTES: "1024",
  ...overrides,
});

test("health is public and returns the service schema version", async () => {
  const response = await memoryWorker.fetch(
    new Request("https://memory.example/health"),
    env(),
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    service: "qudron-memory",
    schema_version: "1",
  });
});

test("all non-health routes require the bearer token", async () => {
  const response = await memoryWorker.fetch(
    new Request("https://memory.example/v1/context?project_id=qudron"),
    env(),
  );
  assert.equal(response.status, 401);
});

test("POST endpoints reject non-JSON content before touching storage", async () => {
  const response = await memoryWorker.fetch(
    new Request("https://memory.example/v1/projects", {
      method: "POST",
      headers: { Authorization: "Bearer test-memory-token", "Content-Type": "text/plain" },
      body: "not-json",
    }),
    env(),
  );
  assert.equal(response.status, 415);
  assert.deepEqual(await response.json(), { error: "application_json_required" });
});

test("streaming body limit rejects oversized chunked requests", async () => {
  const response = await memoryWorker.fetch(
    new Request("https://memory.example/v1/projects", {
      method: "POST",
      headers: {
        Authorization: "Bearer test-memory-token",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ project_id: "x", padding: "x".repeat(2048) }),
    }),
    env(),
  );
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: "payload_too_large" });
});

test("malformed JSON is rejected without a database dependency", async () => {
  const response = await memoryWorker.fetch(
    new Request("https://memory.example/v1/projects", {
      method: "POST",
      headers: {
        Authorization: "Bearer test-memory-token",
        "Content-Type": "application/json",
      },
      body: "{",
    }),
    env(),
  );
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: "invalid_json" });
});
