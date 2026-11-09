PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'discovered',
  summary TEXT NOT NULL DEFAULT '',
  current_phase TEXT NOT NULL DEFAULT '',
  success_criteria_json TEXT NOT NULL DEFAULT '[]',
  constraints_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
  agent_id TEXT PRIMARY KEY,
  project_id TEXT,
  role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  current_task_id TEXT,
  checkpoint_json TEXT NOT NULL DEFAULT '{}',
  last_verified_output_json TEXT NOT NULL DEFAULT '{}',
  blockers_json TEXT NOT NULL DEFAULT '[]',
  next_action TEXT NOT NULL DEFAULT '',
  model_provider TEXT,
  model_name TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_project_status ON agents(project_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_current_task ON agents(current_task_id);

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  parent_task_id TEXT,
  assigned_agent_id TEXT,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  priority INTEGER NOT NULL DEFAULT 50,
  dependencies_json TEXT NOT NULL DEFAULT '[]',
  attempt INTEGER NOT NULL DEFAULT 0,
  checkpoint_json TEXT NOT NULL DEFAULT '{}',
  verification_json TEXT NOT NULL DEFAULT '{}',
  artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  usage_json TEXT NOT NULL DEFAULT '{}',
  blocker TEXT NOT NULL DEFAULT '',
  next_action TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_agent_status ON tasks(assigned_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);

CREATE TABLE IF NOT EXISTS memory_events (
  event_id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  project_id TEXT,
  agent_id TEXT,
  task_id TEXT,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  summary TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  occurred_at TEXT NOT NULL,
  stored_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_project_time ON memory_events(project_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_agent_time ON memory_events(agent_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_task_time ON memory_events(task_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_scope_time ON memory_events(scope, scope_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  decision TEXT NOT NULL,
  rationale TEXT NOT NULL DEFAULT '',
  alternatives_json TEXT NOT NULL DEFAULT '[]',
  constraints_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  decided_by TEXT NOT NULL,
  source_ref TEXT NOT NULL DEFAULT '',
  decided_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_project_time ON decisions(project_id, decided_at DESC);

CREATE TABLE IF NOT EXISTS conversation_notes (
  note_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  source_ref TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL,
  key_facts_json TEXT NOT NULL DEFAULT '[]',
  decisions_json TEXT NOT NULL DEFAULT '[]',
  open_loops_json TEXT NOT NULL DEFAULT '[]',
  updated_by TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_notes_project_time ON conversation_notes(project_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_notes_conversation ON conversation_notes(conversation_id);
