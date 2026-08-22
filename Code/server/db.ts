import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DB_PATH = path.join(__dirname, '..', 'data.db');

let db: Database.Database;

// ============================================================================
// 极简迁移机制（PRAGMA user_version）
// ----------------------------------------------------------------------------
// 每做一个 schema 变更就追加一个迁移步骤：修改 SCHEMA_VERSION、在 MIGRATIONS
// 末尾加一段 SQL，重启后端即自动应用，不再需要"删 data.db 重建"。
// 只在真正改表结构/索引时加步骤；纯代码改动不在此列。
// ============================================================================

/** 当前期望的 schema 版本（每新增一个迁移步骤 +1） */
const SCHEMA_VERSION = 1;

/** 按版本号递增的迁移步骤；下标 = 目标版本（第 n 步把库升到 n）。只允许 SQLite 支持的 DDL。 */
const MIGRATIONS: { version: number; sql: string }[] = [
  // 版本 1：基线（初始 5 张表 + 2 索引）。这一步既建空库也把旧库标记为己迁移。
  {
    version: 1,
    sql: `
      CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT    UNIQUE NOT NULL,
        password_hash TEXT    NOT NULL,
        nickname      TEXT    DEFAULT '',
        grade         TEXT    DEFAULT '',
        major         TEXT    DEFAULT '',
        interests     TEXT    DEFAULT '[]',
        skills        TEXT    DEFAULT '[]',
        bio           TEXT    DEFAULT '',
        created_at    TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at    TEXT    DEFAULT (datetime('now', 'localtime'))
      );

      CREATE TABLE IF NOT EXISTS favorites (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        advisor_id TEXT    NOT NULL,
        created_at TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, advisor_id)
      );

      CREATE TABLE IF NOT EXISTS user_settings (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER UNIQUE NOT NULL,
        bg_theme     TEXT    DEFAULT 'pure-black',
        bg_color     TEXT    DEFAULT '#000000',
        default_sort TEXT    DEFAULT 'match',
        card_density TEXT    DEFAULT 'standard',
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS search_history (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        query         TEXT    NOT NULL,
        results_count INTEGER DEFAULT 0,
        created_at    TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS chat_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        session_id TEXT    NOT NULL,
        role       TEXT    NOT NULL,
        content    TEXT    NOT NULL,
        created_at TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_search_history_user
        ON search_history(user_id, created_at DESC);

      CREATE INDEX IF NOT EXISTS idx_chat_history_session
        ON chat_history(user_id, session_id, created_at);
    `,
  },
];

/**
 * 应用从当前 user_version 到 SCHEMA_VERSION 的迁移。
 * 每个版本一个事务，寄希望于迁移步骤本身是幂等/正确的；失败即抛错阻止启动，
 * 避免"半迁移"状态。
 */
function applyMigrations(database: Database.Database): void {
  const current = database.pragma('user_version', { simple: true }) as number;
  for (const step of MIGRATIONS) {
    if (step.version <= current) continue;
    // SQLite 多条语句在一个 exec 中执行不在同一事务里，故每条整段包一层显式事务。
    database.transaction(() => {
      database.exec(step.sql);
      database.pragma(`user_version = ${step.version}`);
    })();
  }
}

export function getDb(): Database.Database {
  if (!db) {
    db = new Database(DB_PATH);
    db.pragma('journal_mode = WAL');
    db.pragma('foreign_keys = ON');
    applyMigrations(db);
  }
  return db;
}