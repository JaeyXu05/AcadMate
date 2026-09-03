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
const SCHEMA_VERSION = 21;

const PRODUCTIVITY_DDL = `
      CREATE TABLE IF NOT EXISTS report_preferences (
        user_id          INTEGER PRIMARY KEY,
        daily_enabled    INTEGER NOT NULL DEFAULT 0,
        weekly_enabled   INTEGER NOT NULL DEFAULT 1,
        monthly_enabled  INTEGER NOT NULL DEFAULT 1,
        email_enabled    INTEGER NOT NULL DEFAULT 0,
        daily_time       TEXT    NOT NULL DEFAULT '20:00',
        weekly_day       INTEGER NOT NULL DEFAULT 5,
        monthly_day      INTEGER NOT NULL DEFAULT 1,
        timezone         TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
        updated_at       TEXT    DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS progress_reports (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL,
        period_type      TEXT    NOT NULL,
        period_start     TEXT    NOT NULL,
        period_end       TEXT    NOT NULL,
        title            TEXT    NOT NULL,
        content_markdown TEXT    NOT NULL,
        metrics_json     TEXT    NOT NULL DEFAULT '{}',
        evidence_refs    TEXT    NOT NULL DEFAULT '[]',
        generation_json  TEXT    NOT NULL DEFAULT '{}',
        review_status    TEXT    NOT NULL DEFAULT 'PASS',
        delivery_status  TEXT    NOT NULL DEFAULT 'draft',
        delivered_at     TEXT,
        created_at       TEXT    DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, period_type, period_start, period_end)
      );

      CREATE INDEX IF NOT EXISTS idx_progress_reports_user
        ON progress_reports(user_id, created_at DESC);

      CREATE TABLE IF NOT EXISTS plans (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        title             TEXT    NOT NULL,
        description       TEXT    NOT NULL DEFAULT '',
        status            TEXT    NOT NULL DEFAULT 'todo',
        priority          TEXT    NOT NULL DEFAULT 'medium',
        start_at          TEXT,
        due_at            TEXT,
        estimated_minutes INTEGER NOT NULL DEFAULT 60,
        actual_minutes    INTEGER NOT NULL DEFAULT 0,
        reminder_at       TEXT,
        email_reminder    INTEGER NOT NULL DEFAULT 0,
        source            TEXT    NOT NULL DEFAULT 'user',
        created_at        TEXT    DEFAULT (datetime('now','localtime')),
        updated_at        TEXT    DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_plans_user_due
        ON plans(user_id, status, due_at);

      CREATE TABLE IF NOT EXISTS email_outbox (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        recipient    TEXT    NOT NULL,
        subject      TEXT    NOT NULL,
        body         TEXT    NOT NULL,
        kind         TEXT    NOT NULL,
        status       TEXT    NOT NULL DEFAULT 'queued',
        scheduled_at TEXT,
        sent_at      TEXT,
        error        TEXT,
        attachments_json TEXT NOT NULL DEFAULT '[]',
        created_at   TEXT    DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_email_outbox_status
        ON email_outbox(status, scheduled_at);

      CREATE TABLE IF NOT EXISTS email_accounts (
        user_id              INTEGER PRIMARY KEY,
        smtp_host            TEXT NOT NULL DEFAULT '',
        smtp_port            INTEGER NOT NULL DEFAULT 465,
        smtp_secure          INTEGER NOT NULL DEFAULT 1,
        smtp_user            TEXT NOT NULL DEFAULT '',
        smtp_from            TEXT NOT NULL DEFAULT '',
        smtp_pass_encrypted  TEXT NOT NULL DEFAULT '',
        smtp_remember        INTEGER NOT NULL DEFAULT 0,
        imap_host            TEXT NOT NULL DEFAULT '',
        imap_port            INTEGER NOT NULL DEFAULT 993,
        imap_secure          INTEGER NOT NULL DEFAULT 1,
        imap_user            TEXT NOT NULL DEFAULT '',
        imap_mailbox         TEXT NOT NULL DEFAULT 'INBOX',
        imap_pass_encrypted  TEXT NOT NULL DEFAULT '',
        imap_remember        INTEGER NOT NULL DEFAULT 0,
        imap_same_as_smtp   INTEGER NOT NULL DEFAULT 0,
        updated_at           TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );
`;

const RESEARCH_DDL = `
      CREATE TABLE IF NOT EXISTS research_projects (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'idea',
        goal        TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at  TEXT DEFAULT (datetime('now','localtime')),
        updated_at  TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_research_projects_user
        ON research_projects(user_id, updated_at DESC);

      CREATE TABLE IF NOT EXISTS conversations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        project_id      INTEGER,
        surface         TEXT NOT NULL DEFAULT 'research',
        title           TEXT NOT NULL DEFAULT '新对话',
        status          TEXT NOT NULL DEFAULT 'active',
        active_goal_id  INTEGER,
        agent_thread_id INTEGER,
        metadata_json   TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        updated_at      TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (project_id) REFERENCES research_projects(id) ON DELETE SET NULL
      );

      CREATE INDEX IF NOT EXISTS idx_conversations_user
        ON conversations(user_id, updated_at DESC);

      CREATE TABLE IF NOT EXISTS conversation_goals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        user_id         INTEGER NOT NULL,
        version         INTEGER NOT NULL,
        title           TEXT NOT NULL,
        description     TEXT NOT NULL DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'active',
        source          TEXT NOT NULL DEFAULT 'user',
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(conversation_id, version)
      );

      CREATE INDEX IF NOT EXISTS idx_conversation_goals_user
        ON conversation_goals(user_id, conversation_id, version DESC);

      CREATE TABLE IF NOT EXISTS conversation_messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        user_id         INTEGER NOT NULL,
        role            TEXT NOT NULL,
        content         TEXT NOT NULL,
        metadata_json   TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_conversation_messages
        ON conversation_messages(conversation_id, created_at);
`;

const PRESENTATION_DDL = `
      CREATE TABLE IF NOT EXISTS presentation_jobs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        report_id    INTEGER NOT NULL,
        status       TEXT NOT NULL DEFAULT 'queued',
        template     TEXT NOT NULL DEFAULT 'group_meeting',
        slide_count  INTEGER NOT NULL DEFAULT 8,
        file_path    TEXT,
        title        TEXT NOT NULL DEFAULT '',
        error        TEXT,
        created_at   TEXT DEFAULT (datetime('now','localtime')),
        completed_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (report_id) REFERENCES progress_reports(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_presentation_jobs_user
        ON presentation_jobs(user_id, created_at DESC);
`;

const SKILL_DDL = `
      CREATE TABLE IF NOT EXISTS custom_skills (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        name            TEXT NOT NULL,
        description     TEXT NOT NULL DEFAULT '',
        prompt_template TEXT NOT NULL DEFAULT '',
        trigger_mode    TEXT NOT NULL DEFAULT 'manual_or_suggest',
        allowed_tools   TEXT NOT NULL DEFAULT '[]',
        permissions     TEXT NOT NULL DEFAULT '[]',
        status          TEXT NOT NULL DEFAULT 'draft',
        version         INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        updated_at      TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_custom_skills_user
        ON custom_skills(user_id, updated_at DESC);
`;

const INTEGRATIONS_DDL = `
      CREATE TABLE IF NOT EXISTS integration_accounts (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL,
        provider         TEXT NOT NULL,
        external_user_id TEXT,
        status           TEXT NOT NULL DEFAULT 'disconnected',
        config_json      TEXT NOT NULL DEFAULT '{}',
        secret_ciphertext TEXT,
        last_sync_at     TEXT,
        last_error       TEXT,
        created_at       TEXT DEFAULT (datetime('now','localtime')),
        updated_at       TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, provider)
      );

      CREATE TABLE IF NOT EXISTS integration_items (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        integration_id INTEGER NOT NULL,
        user_id        INTEGER NOT NULL,
        external_id    TEXT NOT NULL,
        item_type      TEXT NOT NULL DEFAULT 'paper',
        title          TEXT NOT NULL DEFAULT '',
        authors_json   TEXT NOT NULL DEFAULT '[]',
        year           INTEGER,
        doi            TEXT,
        url            TEXT,
        raw_json       TEXT NOT NULL DEFAULT '{}',
        updated_at     TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (integration_id) REFERENCES integration_accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(integration_id, external_id)
      );

      CREATE INDEX IF NOT EXISTS idx_integration_items_user
        ON integration_items(user_id, integration_id, updated_at DESC);
`;

const PAPER_SEARCH_DDL = `
      CREATE TABLE IF NOT EXISTS paper_search_sessions (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        agent_session_id  INTEGER NOT NULL,
        query             TEXT NOT NULL,
        source            TEXT NOT NULL,
        created_at        TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, agent_session_id)
      );

      CREATE INDEX IF NOT EXISTS idx_paper_search_sessions_user
        ON paper_search_sessions(user_id, created_at DESC);
`;

const PDF_ANALYSIS_DDL = `
      CREATE TABLE IF NOT EXISTS pdf_analysis_jobs (
        job_id       TEXT PRIMARY KEY,
        user_id      INTEGER NOT NULL,
        document_id  TEXT NOT NULL,
        filename     TEXT NOT NULL DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'queued',
        result_json  TEXT,
        error        TEXT,
        created_at   TEXT DEFAULT (datetime('now', 'localtime')),
        started_at   TEXT,
        completed_at TEXT,
        updated_at   TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_pdf_analysis_jobs_user
        ON pdf_analysis_jobs(user_id, created_at DESC);

      CREATE INDEX IF NOT EXISTS idx_pdf_analysis_jobs_active
        ON pdf_analysis_jobs(user_id, document_id, status);
`;

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
  {
    version: 2,
    sql: `
      CREATE TABLE IF NOT EXISTS growth_state (
        user_id         INTEGER PRIMARY KEY,
        matched_mentors TEXT    NOT NULL DEFAULT '[]',
        directions      TEXT    NOT NULL DEFAULT '[]',
        read_papers     TEXT    NOT NULL DEFAULT '[]',
        updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );
    `,
  },
  {
    version: 3,
    sql: `
      ALTER TABLE growth_state ADD COLUMN verified_experiences TEXT NOT NULL DEFAULT '[]';
      ALTER TABLE growth_state ADD COLUMN artifacts TEXT NOT NULL DEFAULT '[]';
      ALTER TABLE growth_state ADD COLUMN research_tasks TEXT NOT NULL DEFAULT '[]';
      ALTER TABLE growth_state ADD COLUMN direction_hypotheses TEXT NOT NULL DEFAULT '[]';
    `,
  },
  {
    version: 4,
    sql: `
      ALTER TABLE growth_state ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0;

      CREATE TABLE IF NOT EXISTS growth_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        verb            TEXT    NOT NULL,
        object_type     TEXT    NOT NULL,
        object_id       TEXT    NOT NULL,
        result_json     TEXT    NOT NULL DEFAULT '{}',
        context_json    TEXT    NOT NULL DEFAULT '{}',
        source_run_id   TEXT,
        source_skill_id TEXT,
        created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_growth_events_user
        ON growth_events(user_id, created_at DESC);

      CREATE TABLE IF NOT EXISTS run_artifacts (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER NOT NULL,
        run_id         TEXT    NOT NULL,
        trace_id       TEXT,
        skill_id       TEXT    NOT NULL,
        query          TEXT,
        review_status  TEXT,
        payload_json   TEXT    NOT NULL,
        created_at     TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, run_id, skill_id)
      );

      CREATE INDEX IF NOT EXISTS idx_run_artifacts_user
        ON run_artifacts(user_id, created_at DESC);

      CREATE TABLE IF NOT EXISTS research_documents (
        document_id    TEXT    PRIMARY KEY,
        user_id        INTEGER NOT NULL,
        content_hash   TEXT    NOT NULL,
        original_name  TEXT,
        stored_path    TEXT    NOT NULL,
        page_count     INTEGER,
        extracted_text TEXT,
        parse_status   TEXT    NOT NULL DEFAULT 'uploaded',
        created_at     TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at     TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, content_hash)
      );

      CREATE TABLE IF NOT EXISTS pending_growth_writes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        skill_id    TEXT    NOT NULL,
        run_id      TEXT,
        trace_id    TEXT,
        query       TEXT,
        payload_json TEXT   NOT NULL DEFAULT '{}',
        status      TEXT    NOT NULL DEFAULT 'polling',
        created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_pending_growth_writes_status
        ON pending_growth_writes(status, updated_at);

      ALTER TABLE search_history ADD COLUMN run_id TEXT;
      ALTER TABLE search_history ADD COLUMN trace_id TEXT;
    `,
  },
  {
    version: 5,
    sql: `
      ALTER TABLE pending_growth_writes ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
      ALTER TABLE pending_growth_writes ADD COLUMN locked_at TEXT;
      ALTER TABLE pending_growth_writes ADD COLUMN last_error TEXT;

      CREATE UNIQUE INDEX IF NOT EXISTS idx_growth_events_run_skill
        ON growth_events(user_id, source_skill_id, source_run_id, verb)
        WHERE source_run_id IS NOT NULL AND source_run_id != '';

      CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_growth_trace
        ON pending_growth_writes(user_id, skill_id, trace_id)
        WHERE trace_id IS NOT NULL AND trace_id != '';

      CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_growth_run
        ON pending_growth_writes(user_id, skill_id, run_id)
        WHERE run_id IS NOT NULL AND run_id != '';
    `,
  },
  // 版本 6：Mission Replay（从 feature/ui-search-agent 迁入，原该分支编号为 2）
  {
    version: 6,
    sql: `
      CREATE TABLE IF NOT EXISTS missions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        trace_id    TEXT    NOT NULL,
        query       TEXT    NOT NULL,
        status      TEXT    DEFAULT '',
        goal        TEXT    DEFAULT '',
        advisor_ids TEXT    DEFAULT '[]',
        source      TEXT    DEFAULT '',
        created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS mission_events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id    INTEGER NOT NULL,
        seq           INTEGER NOT NULL,
        event_type    TEXT    NOT NULL,
        stage         TEXT    DEFAULT '',
        sender        TEXT    DEFAULT '',
        receiver      TEXT    DEFAULT '',
        payload       TEXT    DEFAULT '{}',
        evidence_refs TEXT    DEFAULT '[]',
        state_version INTEGER,
        created_at    TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_missions_user
        ON missions(user_id, created_at DESC);

      CREATE INDEX IF NOT EXISTS idx_mission_events_seq
        ON mission_events(mission_id, seq);
    `,
  },
  {
    version: 7,
    sql: `
      CREATE TABLE IF NOT EXISTS advisor_feedback (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        advisor_id TEXT    NOT NULL,
        feedback   TEXT    NOT NULL DEFAULT 'dislike',
        created_at TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, advisor_id)
      );

      CREATE INDEX IF NOT EXISTS idx_feedback_user
        ON advisor_feedback(user_id, created_at DESC);
    `,
  },
  {
    version: 8,
    sql: `
      CREATE TABLE IF NOT EXISTS report_preferences (
        user_id          INTEGER PRIMARY KEY,
        daily_enabled    INTEGER NOT NULL DEFAULT 0,
        weekly_enabled   INTEGER NOT NULL DEFAULT 1,
        monthly_enabled  INTEGER NOT NULL DEFAULT 1,
        email_enabled    INTEGER NOT NULL DEFAULT 0,
        daily_time       TEXT    NOT NULL DEFAULT '20:00',
        weekly_day       INTEGER NOT NULL DEFAULT 5,
        monthly_day      INTEGER NOT NULL DEFAULT 1,
        timezone         TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
        updated_at       TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS progress_reports (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL,
        period_type      TEXT    NOT NULL,
        period_start     TEXT    NOT NULL,
        period_end       TEXT    NOT NULL,
        title            TEXT    NOT NULL,
        content_markdown TEXT    NOT NULL,
        metrics_json     TEXT    NOT NULL DEFAULT '{}',
        evidence_refs    TEXT    NOT NULL DEFAULT '[]',
        review_status    TEXT    NOT NULL DEFAULT 'PASS',
        delivery_status  TEXT    NOT NULL DEFAULT 'draft',
        delivered_at     TEXT,
        created_at       TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, period_type, period_start, period_end)
      );

      CREATE INDEX IF NOT EXISTS idx_progress_reports_user
        ON progress_reports(user_id, created_at DESC);

      CREATE TABLE IF NOT EXISTS plans (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        title             TEXT    NOT NULL,
        description       TEXT    NOT NULL DEFAULT '',
        status            TEXT    NOT NULL DEFAULT 'todo',
        priority          TEXT    NOT NULL DEFAULT 'medium',
        start_at          TEXT,
        due_at            TEXT,
        estimated_minutes INTEGER NOT NULL DEFAULT 60,
        actual_minutes    INTEGER NOT NULL DEFAULT 0,
        reminder_at       TEXT,
        email_reminder    INTEGER NOT NULL DEFAULT 0,
        source            TEXT    NOT NULL DEFAULT 'user',
        created_at        TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at        TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_plans_user_due
        ON plans(user_id, status, due_at);

      CREATE TABLE IF NOT EXISTS email_outbox (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        recipient    TEXT    NOT NULL,
        subject      TEXT    NOT NULL,
        body         TEXT    NOT NULL,
        kind         TEXT    NOT NULL,
        status       TEXT    NOT NULL DEFAULT 'queued',
        scheduled_at TEXT,
        sent_at      TEXT,
        error        TEXT,
        created_at   TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_email_outbox_status
        ON email_outbox(status, scheduled_at);
    `,
  },
  {
    version: 9,
    sql: `
      ALTER TABLE plans ADD COLUMN completed_at TEXT;
      ALTER TABLE email_outbox ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
      ALTER TABLE email_outbox ADD COLUMN last_attempt_at TEXT;
      CREATE INDEX IF NOT EXISTS idx_plans_user_completed
        ON plans(user_id, completed_at);
    `,
  },
  // 版本 10：旧库 user_version 已到 8/9 但 8 的表未真正建出时，幂等补建。
  {
    version: 10,
    sql: PRODUCTIVITY_DDL,
  },
  {
    version: 11,
    sql: `
      ALTER TABLE progress_reports ADD COLUMN generation_json TEXT NOT NULL DEFAULT '{}';
    `,
  },
  {
    version: 12,
    sql: RESEARCH_DDL,
  },
  {
    version: 13,
    sql: PRESENTATION_DDL,
  },
  {
    version: 14,
    sql: SKILL_DDL,
  },
  {
    version: 15,
    sql: INTEGRATIONS_DDL,
  },
  {
    version: 16,
    sql: PAPER_SEARCH_DDL,
  },
  {
    version: 17,
    sql: `
      CREATE TABLE IF NOT EXISTS email_accounts (
        user_id              INTEGER PRIMARY KEY,
        smtp_host            TEXT NOT NULL DEFAULT '',
        smtp_port            INTEGER NOT NULL DEFAULT 465,
        smtp_secure          INTEGER NOT NULL DEFAULT 1,
        smtp_user            TEXT NOT NULL DEFAULT '',
        smtp_from            TEXT NOT NULL DEFAULT '',
        smtp_pass_encrypted  TEXT NOT NULL DEFAULT '',
        smtp_remember        INTEGER NOT NULL DEFAULT 0,
        imap_host            TEXT NOT NULL DEFAULT '',
        imap_port            INTEGER NOT NULL DEFAULT 993,
        imap_secure          INTEGER NOT NULL DEFAULT 1,
        imap_user            TEXT NOT NULL DEFAULT '',
        imap_mailbox         TEXT NOT NULL DEFAULT 'INBOX',
        imap_pass_encrypted  TEXT NOT NULL DEFAULT '',
        imap_remember        INTEGER NOT NULL DEFAULT 0,
        updated_at           TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
      );
    `,
  },
  {
    version: 18,
    sql: `ALTER TABLE email_accounts ADD COLUMN imap_same_as_smtp INTEGER NOT NULL DEFAULT 0;`,
  },
  {
    version: 19,
    sql: `UPDATE email_accounts SET imap_same_as_smtp = 0 WHERE imap_same_as_smtp = 1;`,
  },
  {
    version: 20,
    sql: PDF_ANALYSIS_DDL,
  },
  {
    version: 21,
    sql: `ALTER TABLE email_outbox ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]';`,
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
    try {
      // SQLite 多条语句在一个 exec 中执行不在同一事务里，故每条整段包一层显式事务。
      database.transaction(() => {
        database.exec(step.sql);
        database.pragma(`user_version = ${step.version}`);
      })();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // 重复列 / 表已存在：把版本推上去，缺的表和列交给 ensureProductivitySchema。
      if (/duplicate column name|already exists|no such table/i.test(msg)) {
        database.pragma(`user_version = ${step.version}`);
        continue;
      }
      throw err;
    }
  }
  ensureProductivitySchema(database);
}

function tableExists(database: Database.Database, name: string): boolean {
  const row = database.prepare(
    `SELECT name FROM sqlite_master WHERE type='table' AND name=?`,
  ).get(name) as { name?: string } | undefined;
  return Boolean(row?.name);
}

function ensureColumn(database: Database.Database, table: string, column: string, ddl: string): void {
  if (!tableExists(database, table)) return;
  const cols = database.pragma(`table_info(${table})`) as Array<{ name: string }>;
  if (cols.some((col) => col.name === column)) return;
  database.exec(`ALTER TABLE ${table} ADD COLUMN ${ddl}`);
}

/** 计划/报告/发件箱表不存在时补建，不依赖 user_version 是否已到 8/9。 */
export function ensureProductivitySchema(database: Database.Database): void {
  database.exec(PRODUCTIVITY_DDL);
  ensureColumn(database, 'plans', 'completed_at', 'completed_at TEXT');
  ensureColumn(database, 'email_outbox', 'attempt_count', 'attempt_count INTEGER NOT NULL DEFAULT 0');
  ensureColumn(database, 'email_outbox', 'last_attempt_at', 'last_attempt_at TEXT');
  ensureColumn(database, 'email_outbox', 'attachments_json', "attachments_json TEXT NOT NULL DEFAULT '[]'");
  ensureColumn(database, 'progress_reports', 'generation_json', "generation_json TEXT NOT NULL DEFAULT '{}'");
  if (tableExists(database, 'plans')) {
    database.exec(`CREATE INDEX IF NOT EXISTS idx_plans_user_completed ON plans(user_id, completed_at)`);
  }
  database.exec(RESEARCH_DDL);
  database.exec(PRESENTATION_DDL);
  database.exec(SKILL_DDL);
  database.exec(INTEGRATIONS_DDL);
  database.exec(PAPER_SEARCH_DDL);
  database.exec(PDF_ANALYSIS_DDL);
}

export function getDb(): Database.Database {
  if (!db) {
    const conn = new Database(DB_PATH);
    conn.pragma('journal_mode = WAL');
    conn.pragma('foreign_keys = ON');
    applyMigrations(conn);
    db = conn;
  }
  return db;
}
