import Database from "better-sqlite3";
import path from "path";

const DB_PATH = path.join(process.cwd(), "registry.db");

let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!_db) {
    _db = new Database(DB_PATH);
    _db.pragma("journal_mode = WAL");
    _db.pragma("busy_timeout = 5000");
    _db.exec(`
      CREATE TABLE IF NOT EXISTS agents (
        did TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        pod_url TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT 'person',
        capabilities TEXT DEFAULT '[]',
        username TEXT DEFAULT '',
        display_name TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        registered_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `);
  }
  return _db;
}

export interface AgentRecord {
  did: string;
  name: string;
  pod_url: string;
  entity_type: string;
  capabilities: string[];
  username: string;
  display_name: string;
  bio: string;
  registered_at: string;
  updated_at: string;
}

interface AgentRow {
  did: string;
  name: string;
  pod_url: string;
  entity_type: string;
  capabilities: string;
  username: string;
  display_name: string;
  bio: string;
  registered_at: string;
  updated_at: string;
}

function rowToAgent(row: AgentRow): AgentRecord {
  return {
    ...row,
    capabilities: JSON.parse(row.capabilities || "[]"),
  };
}

export function registerAgent(agent: {
  did: string;
  name: string;
  pod_url: string;
  entity_type?: string;
  capabilities?: string[];
  username?: string;
  display_name?: string;
  bio?: string;
}): AgentRecord {
  const db = getDb();
  const now = new Date().toISOString();
  const caps = JSON.stringify(agent.capabilities || []);

  db.prepare(`
    INSERT INTO agents (did, name, pod_url, entity_type, capabilities, username, display_name, bio, registered_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(did) DO UPDATE SET
      name = excluded.name,
      pod_url = excluded.pod_url,
      entity_type = excluded.entity_type,
      capabilities = excluded.capabilities,
      username = excluded.username,
      display_name = excluded.display_name,
      bio = excluded.bio,
      updated_at = excluded.updated_at
  `).run(
    agent.did,
    agent.name,
    agent.pod_url,
    agent.entity_type || "person",
    caps,
    agent.username || "",
    agent.display_name || "",
    agent.bio || "",
    now,
    now,
  );

  return lookupAgent(agent.did)!;
}

export function deregisterAgent(did: string): boolean {
  const db = getDb();
  const result = db.prepare("DELETE FROM agents WHERE did = ?").run(did);
  return result.changes > 0;
}

export function listAgents(entityType?: string): AgentRecord[] {
  const db = getDb();
  if (entityType) {
    const rows = db.prepare(
      "SELECT * FROM agents WHERE entity_type = ? ORDER BY display_name, name",
    ).all(entityType) as AgentRow[];
    return rows.map(rowToAgent);
  }
  const rows = db.prepare(
    "SELECT * FROM agents ORDER BY display_name, name",
  ).all() as AgentRow[];
  return rows.map(rowToAgent);
}

export function searchAgents(q: string, entityType?: string): AgentRecord[] {
  const db = getDb();
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return listAgents(entityType);

  // SQLite LIKE-based search for each word (OR match)
  let rows: AgentRow[];
  if (entityType) {
    rows = db.prepare(
      "SELECT * FROM agents WHERE entity_type = ? ORDER BY display_name, name",
    ).all(entityType) as AgentRow[];
  } else {
    rows = db.prepare(
      "SELECT * FROM agents ORDER BY display_name, name",
    ).all() as AgentRow[];
  }

  return rows.filter((row) => {
    const searchable = `${row.name} ${row.display_name} ${row.bio} ${row.username} ${row.capabilities}`.toLowerCase();
    return words.some((w) => searchable.includes(w));
  }).map(rowToAgent);
}

export function lookupAgent(did: string): AgentRecord | null {
  const db = getDb();
  const row = db.prepare("SELECT * FROM agents WHERE did = ?").get(did) as AgentRow | undefined;
  return row ? rowToAgent(row) : null;
}

export function getStats(): { total: number; people: number; organizations: number; government: number } {
  const db = getDb();
  const total = (db.prepare("SELECT COUNT(*) as c FROM agents").get() as { c: number }).c;
  const people = (db.prepare("SELECT COUNT(*) as c FROM agents WHERE entity_type = 'person'").get() as { c: number }).c;
  const organizations = (db.prepare("SELECT COUNT(*) as c FROM agents WHERE entity_type = 'organization'").get() as { c: number }).c;
  const government = (db.prepare("SELECT COUNT(*) as c FROM agents WHERE entity_type = 'government'").get() as { c: number }).c;
  return { total, people, organizations, government };
}

export function resetAll(): void {
  const db = getDb();
  db.prepare("DELETE FROM agents").run();
}
