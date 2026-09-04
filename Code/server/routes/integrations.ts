import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto';
import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ensureProductivitySchema, getDb } from '../db';

export const integrationsRouter = Router();
integrationsRouter.use(authMiddleware);

function encryptionKey(): Buffer {
  return createHash('sha256').update(String(process.env.JWT_SECRET || 'paper-claw-local-secret')).digest();
}

function encryptSecret(value: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', encryptionKey(), iv);
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), encrypted]).toString('base64');
}

function decryptSecret(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const bytes = Buffer.from(value, 'base64');
    const decipher = createDecipheriv('aes-256-gcm', encryptionKey(), bytes.subarray(0, 12));
    decipher.setAuthTag(bytes.subarray(12, 28));
    return Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString('utf8');
  } catch { return null; }
}

function zoteroUrl(path: string): string {
  return `https://api.zotero.org${path}`;
}

function mapAccount(row: any) {
  return row ? {
    id: row.id,
    provider: row.provider,
    external_user_id: row.external_user_id,
    status: row.status,
    config: safeJson(row.config_json),
    last_sync_at: row.last_sync_at,
    last_error: row.last_error,
    created_at: row.created_at,
    updated_at: row.updated_at,
  } : null;
}

function safeJson(value: unknown): Record<string, unknown> {
  if (typeof value !== 'string') return {};
  try { const parsed = JSON.parse(value); return parsed && typeof parsed === 'object' ? parsed : {}; } catch { return {}; }
}

function account(userId: number, provider = 'zotero'): any | undefined {
  return getDb().prepare('SELECT * FROM integration_accounts WHERE user_id=? AND provider=?').get(userId, provider) as any;
}

integrationsRouter.get('/', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const rows = getDb().prepare('SELECT * FROM integration_accounts WHERE user_id=? ORDER BY provider').all(req.userId!) as any[];
  res.json(rows.map(mapAccount));
});

integrationsRouter.post('/zotero/connect', async (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const libraryId = String(req.body?.library_id || '').trim();
  const apiKey = String(req.body?.api_key || '').trim();
  if (!libraryId) { res.status(400).json({ message: '请填写 Zotero Library ID' }); return; }
  if (!apiKey) { res.status(400).json({ message: '请填写 Zotero API Key' }); return; }
  if (!/^\d+$/.test(libraryId)) {
    res.status(400).json({ message: 'Zotero Library ID 应为数字；请到 Zotero 设置页复制你的 User ID' });
    return;
  }
  try {
    const response = await fetch(zoteroUrl(`/users/${encodeURIComponent(libraryId)}/collections?limit=1`), { headers: { 'Zotero-API-Key': apiKey, 'Zotero-API-Version': '3' }, signal: AbortSignal.timeout(12000) });
    if (!response.ok) { res.status(400).json({ message: `Zotero 验证失败（HTTP ${response.status}）` }); return; }
    const db = getDb();
    db.prepare(
      `INSERT INTO integration_accounts (user_id, provider, external_user_id, status, config_json, secret_ciphertext, last_error)
       VALUES (?, 'zotero', ?, 'connected', ?, ?, NULL)
       ON CONFLICT(user_id, provider) DO UPDATE SET external_user_id=excluded.external_user_id, status='connected', config_json=excluded.config_json, secret_ciphertext=excluded.secret_ciphertext, last_error=NULL, updated_at=datetime('now','localtime')`,
    ).run(req.userId!, libraryId, JSON.stringify({ library_type: 'user', api_version: '3' }), encryptSecret(apiKey));
    res.json(mapAccount(account(req.userId!)));
  } catch (error) {
    res.status(502).json({ message: error instanceof Error ? `无法连接 Zotero：${error.message}` : '无法连接 Zotero' });
  }
});

integrationsRouter.get('/zotero/collections', async (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const item = account(req.userId!);
  const key = decryptSecret(item?.secret_ciphertext);
  if (!item || item.status !== 'connected' || !key) { res.status(409).json({ message: '请先连接 Zotero' }); return; }
  try {
    const response = await fetch(zoteroUrl(`/users/${encodeURIComponent(item.external_user_id)}/collections?limit=100&format=json`), { headers: { 'Zotero-API-Key': key, 'Zotero-API-Version': '3' }, signal: AbortSignal.timeout(15000) });
    if (!response.ok) { res.status(response.status).json({ message: `读取 Zotero Collection 失败（HTTP ${response.status}）` }); return; }
    const data = await response.json() as any[];
    res.json(data.map((entry) => ({ id: entry.key, name: entry.data?.name || entry.key, parent: entry.data?.parent || null, item_count: entry.meta?.numItems ?? null })));
  } catch (error) { res.status(502).json({ message: error instanceof Error ? error.message : '读取 Zotero Collection 失败' }); }
});

integrationsRouter.post('/zotero/sync', async (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const item = account(req.userId!);
  const key = decryptSecret(item?.secret_ciphertext);
  if (!item || item.status !== 'connected' || !key) { res.status(409).json({ message: '请先连接 Zotero' }); return; }
  const collection = String(req.body?.collection_id || '').trim();
  const endpoint = collection
    ? `/users/${encodeURIComponent(item.external_user_id)}/collections/${encodeURIComponent(collection)}/items`
    : `/users/${encodeURIComponent(item.external_user_id)}/items`;
  try {
    const response = await fetch(zoteroUrl(`${endpoint}?limit=100&format=json&itemType=-attachment%20||%20note`), { headers: { 'Zotero-API-Key': key, 'Zotero-API-Version': '3' }, signal: AbortSignal.timeout(20000) });
    if (!response.ok) { res.status(response.status).json({ message: `同步 Zotero 失败（HTTP ${response.status}）` }); return; }
    const data = await response.json() as any[];
    const db = getDb();
    const upsert = db.prepare(
      `INSERT INTO integration_items (integration_id, user_id, external_id, item_type, title, authors_json, year, doi, url, raw_json)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(integration_id, external_id) DO UPDATE SET item_type=excluded.item_type, title=excluded.title, authors_json=excluded.authors_json, year=excluded.year, doi=excluded.doi, url=excluded.url, raw_json=excluded.raw_json, updated_at=datetime('now','localtime')`,
    );
    const transaction = db.transaction((entries: any[]) => {
      for (const entry of entries) {
        const info = entry.data || {};
        const creators = Array.isArray(info.creators) ? info.creators.map((creator: any) => [creator.firstName, creator.lastName].filter(Boolean).join(' ')).filter(Boolean) : [];
        const yearMatch = String(info.date || '').match(/\b(19|20)\d{2}\b/);
        upsert.run(item.id, req.userId!, String(entry.key || ''), String(info.itemType || 'paper'), String(info.title || ''), JSON.stringify(creators), yearMatch ? Number(yearMatch[0]) : null, String(info.DOI || ''), String(info.url || ''), JSON.stringify(entry));
      }
    });
    transaction(data);
    db.prepare("UPDATE integration_accounts SET last_sync_at=datetime('now','localtime'), last_error=NULL, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(item.id, req.userId!);
    res.json({ imported: data.length, collection_id: collection || null, synced_at: new Date().toISOString() });
  } catch (error) {
    getDb().prepare("UPDATE integration_accounts SET last_error=?, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(error instanceof Error ? error.message : String(error), item.id, req.userId!);
    res.status(502).json({ message: error instanceof Error ? error.message : '同步 Zotero 失败' });
  }
});

integrationsRouter.delete('/zotero', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  getDb().prepare('DELETE FROM integration_accounts WHERE user_id=? AND provider=\'zotero\'').run(req.userId!);
  res.status(204).end();
});
