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
CREATE INDEX IF NOT EXISTS idx_conversation_notes_project_time
  ON conversation_notes(project_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_notes_conversation
  ON conversation_notes(conversation_id);
