export interface Env {
  DB: D1Database;
  QUDRON_MEMORY_TOKEN: string;
  MEMORY_SCHEMA_VERSION?: string;
  MAX_BODY_BYTES?: string;
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

const isoNow = () => new Date().toISOString();
const asObject = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};

function requiredString(body: Record<string, unknown>, key: string, max = 2000): string | null {
  const value = body[key];
  return typeof value === "string" && value.trim().length > 0 && value.length <= max
    ? value.trim() : null;
}

function jsonField(body: Record<string, unknown>, key: string, fallback: unknown): string {
  const value = body[key] === undefined ? fallback : body[key];
  return JSON.stringify(value);
}

async function safeEqual(a: string, b: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [ha, hb] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const aa = new Uint8Array(ha), bb = new Uint8Array(hb);
  let diff = 0;
  for (let i = 0; i < aa.length; i++) diff |= aa[i] ^ bb[i];
  return diff === 0;
}

async function readBody(request: Request, env: Env): Promise<Record<string, unknown> | Response> {
  const configuredLimit = Number(env.MAX_BODY_BYTES || 65536);
  const limit = Number.isFinite(configuredLimit)
    ? Math.min(262144, Math.max(1024, configuredLimit))
    : 65536;
  const contentType = (request.headers.get("content-type") || "")
    .split(";")[0].trim().toLowerCase();
  if (contentType !== "application/json") return json({ error: "application_json_required" }, 415);

  const declared = Number(request.headers.get("content-length") || 0);
  if (Number.isFinite(declared) && declared > limit) {
    return json({ error: "payload_too_large" }, 413);
  }
  if (!request.body) return json({ error: "invalid_json" }, 400);

  // Enforce the limit while reading, not after request.text() has buffered an
  // unbounded body in memory. This also covers chunked requests without a
  // trustworthy Content-Length header.
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel("payload too large").catch(() => undefined);
        return json({ error: "payload_too_large" }, 413);
      }
      chunks.push(value);
    }
  } catch {
    await reader.cancel().catch(() => undefined);
    return json({ error: "request_body_read_failed" }, 400);
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try { return asObject(JSON.parse(new TextDecoder().decode(bytes))); }
  catch { return json({ error: "invalid_json" }, 400); }
}

async function authorized(request: Request, env: Env): Promise<boolean> {
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  return Boolean(env.QUDRON_MEMORY_TOKEN && token && await safeEqual(token, env.QUDRON_MEMORY_TOKEN));
}

async function upsertProject(body: Record<string, unknown>, env: Env): Promise<Response> {
  const id = requiredString(body, "project_id", 160);
  const name = requiredString(body, "name", 240);
  const actor = requiredString(body, "updated_by", 160);
  if (!id || !name || !actor) return json({ error: "project_id_name_updated_by_required" }, 400);
  const now = isoNow();
  await env.DB.prepare(`INSERT INTO projects
    (project_id,name,status,summary,current_phase,success_criteria_json,constraints_json,metadata_json,updated_by,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(project_id) DO UPDATE SET name=excluded.name,status=excluded.status,summary=excluded.summary,
    current_phase=excluded.current_phase,success_criteria_json=excluded.success_criteria_json,
    constraints_json=excluded.constraints_json,metadata_json=excluded.metadata_json,
    updated_by=excluded.updated_by,updated_at=excluded.updated_at`)
    .bind(id, name, requiredString(body,"status",80) || "discovered",
      typeof body.summary === "string" ? body.summary.slice(0,8000) : "",
      typeof body.current_phase === "string" ? body.current_phase.slice(0,240) : "",
      jsonField(body,"success_criteria",[]), jsonField(body,"constraints",[]),
      jsonField(body,"metadata",{}), actor, now).run();
  return json({ ok: true, project_id: id, updated_at: now });
}

async function upsertAgent(body: Record<string, unknown>, env: Env): Promise<Response> {
  const id = requiredString(body, "agent_id", 160);
  const role = requiredString(body, "role", 240);
  const actor = requiredString(body, "updated_by", 160);
  if (!id || !role || !actor) return json({ error: "agent_id_role_updated_by_required" }, 400);
  const now = isoNow();
  await env.DB.prepare(`INSERT INTO agents
    (agent_id,project_id,role,status,current_task_id,checkpoint_json,last_verified_output_json,
     blockers_json,next_action,model_provider,model_name,metadata_json,updated_by,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(agent_id) DO UPDATE SET project_id=excluded.project_id,role=excluded.role,
    status=excluded.status,current_task_id=excluded.current_task_id,checkpoint_json=excluded.checkpoint_json,
    last_verified_output_json=excluded.last_verified_output_json,blockers_json=excluded.blockers_json,
    next_action=excluded.next_action,model_provider=excluded.model_provider,model_name=excluded.model_name,
    metadata_json=excluded.metadata_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at`)
    .bind(id, typeof body.project_id === "string" ? body.project_id : null, role,
      requiredString(body,"status",80) || "idle",
      typeof body.current_task_id === "string" ? body.current_task_id : null,
      jsonField(body,"checkpoint",{}), jsonField(body,"last_verified_output",{}),
      jsonField(body,"blockers",[]), typeof body.next_action === "string" ? body.next_action.slice(0,2000) : "",
      typeof body.model_provider === "string" ? body.model_provider.slice(0,120) : null,
      typeof body.model_name === "string" ? body.model_name.slice(0,160) : null,
      jsonField(body,"metadata",{}), actor, now).run();
  return json({ ok: true, agent_id: id, updated_at: now });
}

async function upsertTask(body: Record<string, unknown>, env: Env): Promise<Response> {
  const id = requiredString(body, "task_id", 160);
  const projectId = requiredString(body, "project_id", 160);
  const title = requiredString(body, "title", 500);
  const actor = requiredString(body, "updated_by", 160);
  if (!id || !projectId || !title || !actor) return json({ error: "task_id_project_id_title_updated_by_required" }, 400);
  const now = isoNow();
  await env.DB.prepare(`INSERT INTO tasks
    (task_id,project_id,parent_task_id,assigned_agent_id,title,status,priority,dependencies_json,attempt,
     checkpoint_json,verification_json,artifact_refs_json,usage_json,blocker,next_action,updated_by,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(task_id) DO UPDATE SET project_id=excluded.project_id,parent_task_id=excluded.parent_task_id,
    assigned_agent_id=excluded.assigned_agent_id,title=excluded.title,status=excluded.status,
    priority=excluded.priority,dependencies_json=excluded.dependencies_json,attempt=excluded.attempt,
    checkpoint_json=excluded.checkpoint_json,verification_json=excluded.verification_json,
    artifact_refs_json=excluded.artifact_refs_json,usage_json=excluded.usage_json,blocker=excluded.blocker,
    next_action=excluded.next_action,updated_by=excluded.updated_by,updated_at=excluded.updated_at`)
    .bind(id, projectId, typeof body.parent_task_id === "string" ? body.parent_task_id : null,
      typeof body.assigned_agent_id === "string" ? body.assigned_agent_id : null, title,
      requiredString(body,"status",80) || "queued",
      Number.isInteger(body.priority) ? Number(body.priority) : 50,
      jsonField(body,"dependencies",[]), Number.isInteger(body.attempt) ? Number(body.attempt) : 0,
      jsonField(body,"checkpoint",{}), jsonField(body,"verification",{}),
      jsonField(body,"artifact_refs",[]), jsonField(body,"usage",{}),
      typeof body.blocker === "string" ? body.blocker.slice(0,2000) : "",
      typeof body.next_action === "string" ? body.next_action.slice(0,2000) : "", actor, now).run();
  return json({ ok: true, task_id: id, updated_at: now });
}

async function appendEvent(body: Record<string, unknown>, env: Env): Promise<Response> {
  const id = requiredString(body, "event_id", 200);
  const scope = requiredString(body, "scope", 40);
  const scopeId = requiredString(body, "scope_id", 200);
  const type = requiredString(body, "event_type", 120);
  const actor = requiredString(body, "actor", 160);
  const summary = requiredString(body, "summary", 4000);
  if (!id || !scope || !scopeId || !type || !actor || !summary)
    return json({ error: "event_id_scope_scope_id_event_type_actor_summary_required" }, 400);
  const occurred = typeof body.occurred_at === "string" && !Number.isNaN(Date.parse(body.occurred_at))
    ? new Date(body.occurred_at).toISOString() : isoNow();
  const result = await env.DB.prepare(`INSERT OR IGNORE INTO memory_events
    (event_id,scope,scope_id,project_id,agent_id,task_id,event_type,actor,summary,details_json,
     evidence_refs_json,occurred_at,stored_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .bind(id, scope, scopeId,
      typeof body.project_id === "string" ? body.project_id : null,
      typeof body.agent_id === "string" ? body.agent_id : null,
      typeof body.task_id === "string" ? body.task_id : null,
      type, actor, summary, jsonField(body,"details",{}), jsonField(body,"evidence_refs",[]),
      occurred, isoNow()).run();
  return json({ ok: true, inserted: result.meta.changes > 0, event_id: id });
}

async function upsertDecision(body: Record<string, unknown>, env: Env): Promise<Response> {
  const id = requiredString(body, "decision_id", 200);
  const projectId = requiredString(body, "project_id", 160);
  const title = requiredString(body, "title", 500);
  const decision = requiredString(body, "decision", 8000);
  const actor = requiredString(body, "decided_by", 160);
  if (!id || !projectId || !title || !decision || !actor)
    return json({ error: "decision_id_project_id_title_decision_decided_by_required" }, 400);
  const at = typeof body.decided_at === "string" && !Number.isNaN(Date.parse(body.decided_at))
    ? new Date(body.decided_at).toISOString() : isoNow();
  await env.DB.prepare(`INSERT INTO decisions
    (decision_id,project_id,title,decision,rationale,alternatives_json,constraints_json,status,decided_by,source_ref,decided_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(decision_id) DO UPDATE SET title=excluded.title,decision=excluded.decision,
    rationale=excluded.rationale,alternatives_json=excluded.alternatives_json,
    constraints_json=excluded.constraints_json,status=excluded.status,decided_by=excluded.decided_by,
    source_ref=excluded.source_ref,decided_at=excluded.decided_at`)
    .bind(id, projectId, title, decision,
      typeof body.rationale === "string" ? body.rationale.slice(0,8000) : "",
      jsonField(body,"alternatives",[]), jsonField(body,"constraints",[]),
      requiredString(body,"status",40) || "active", actor,
      typeof body.source_ref === "string" ? body.source_ref.slice(0,1000) : "", at).run();
  return json({ ok: true, decision_id: id, decided_at: at });
}

async function upsertConversationNote(body: Record<string, unknown>, env: Env): Promise<Response> {
  const id = requiredString(body, "note_id", 200);
  const projectId = requiredString(body, "project_id", 160);
  const conversationId = requiredString(body, "conversation_id", 200);
  const summary = requiredString(body, "summary", 8000);
  const actor = requiredString(body, "updated_by", 160);
  if (!id || !projectId || !conversationId || !summary || !actor)
    return json({ error: "note_id_project_id_conversation_id_summary_updated_by_required" }, 400);
  const at = typeof body.occurred_at === "string" && !Number.isNaN(Date.parse(body.occurred_at))
    ? new Date(body.occurred_at).toISOString() : isoNow();
  await env.DB.prepare("INSERT INTO conversation_notes (note_id,project_id,conversation_id,source_ref,summary,key_facts_json,decisions_json,open_loops_json,updated_by,occurred_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(note_id) DO UPDATE SET source_ref=excluded.source_ref,summary=excluded.summary,key_facts_json=excluded.key_facts_json,decisions_json=excluded.decisions_json,open_loops_json=excluded.open_loops_json,updated_by=excluded.updated_by,occurred_at=excluded.occurred_at")
    .bind(id, projectId, conversationId, typeof body.source_ref === "string" ? body.source_ref.slice(0,1000) : "", summary, jsonField(body,"key_facts",[]), jsonField(body,"decisions",[]), jsonField(body,"open_loops",[]), actor, at).run();
  return json({ ok: true, note_id: id, occurred_at: at });
}
async function getContext(url: URL, env: Env): Promise<Response> {
  const projectId = url.searchParams.get("project_id");
  const agentId = url.searchParams.get("agent_id");
  if (!projectId && !agentId) return json({ error: "project_id_or_agent_id_required" }, 400);
  const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") || 30)));
  const project = projectId
    ? await env.DB.prepare("SELECT * FROM projects WHERE project_id=?").bind(projectId).first()
    : null;
  const agent = agentId
    ? await env.DB.prepare("SELECT * FROM agents WHERE agent_id=?").bind(agentId).first()
    : null;
  const tasks = projectId
    ? await env.DB.prepare("SELECT * FROM tasks WHERE project_id=? ORDER BY priority DESC,updated_at DESC LIMIT ?")
      .bind(projectId, limit).all()
    : await env.DB.prepare("SELECT * FROM tasks WHERE assigned_agent_id=? ORDER BY updated_at DESC LIMIT ?")
      .bind(agentId, limit).all();
  const events = projectId
    ? await env.DB.prepare("SELECT * FROM memory_events WHERE project_id=? OR (scope='project' AND scope_id=?) ORDER BY occurred_at DESC LIMIT ?")
      .bind(projectId, projectId, limit).all()
    : await env.DB.prepare("SELECT * FROM memory_events WHERE agent_id=? OR (scope='agent' AND scope_id=?) ORDER BY occurred_at DESC LIMIT ?")
      .bind(agentId, agentId, limit).all();
  const decisions = projectId
    ? await env.DB.prepare("SELECT * FROM decisions WHERE project_id=? AND status='active' ORDER BY decided_at DESC LIMIT ?")
      .bind(projectId, limit).all()
    : { results: [] };
  const conversationNotes = projectId
    ? await env.DB.prepare("SELECT * FROM conversation_notes WHERE project_id=? ORDER BY occurred_at DESC LIMIT ?")
      .bind(projectId, Math.min(20, limit)).all()
    : { results: [] };
  return json({
    schema_version: env.MEMORY_SCHEMA_VERSION || "1",
    generated_at: isoNow(),
    project, agent,
    tasks: tasks.results || [],
    recent_events: events.results || [],
    active_decisions: decisions.results || [],
    conversation_notes: conversationNotes.results || [],
    note: "Context is a bounded recovery packet, not a claim that every historical conversation has been imported."
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health")
      return json({ ok: true, service: "qudron-memory", schema_version: env.MEMORY_SCHEMA_VERSION || "1" });
    if (!await authorized(request, env)) return json({ error: "unauthorized" }, 401);
    if (request.method === "GET" && url.pathname === "/v1/context") return getContext(url, env);
    if (request.method !== "POST") return json({ error: "not_found" }, 404);
    const body = await readBody(request, env);
    if (body instanceof Response) return body;
    try {
      if (url.pathname === "/v1/projects") return await upsertProject(body, env);
      if (url.pathname === "/v1/agents") return await upsertAgent(body, env);
      if (url.pathname === "/v1/tasks") return await upsertTask(body, env);
      if (url.pathname === "/v1/decisions") return await upsertDecision(body, env);
      if (url.pathname === "/v1/conversations") return await upsertConversationNote(body, env);
      if (url.pathname === "/v1/events") return await appendEvent(body, env);
      return json({ error: "not_found" }, 404);
    } catch {
      return json({ error: "memory_write_failed" }, 500);
    }
  },
};
