import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'crypto';
import { getDb } from '../db';

export interface LlmApiSettings {
  enabled: boolean;
  baseUrl: string;
  model: string;
  apiKeySaved: boolean;
  /** Only returned for the authenticated owner / internal D->A injection. */
  apiKey?: string;
  updatedAt?: string;
}

export interface LlmProviderOverrides {
  llm_api_key?: string;
  llm_base_url?: string;
  llm_model?: string;
}

interface UserSettingsRow {
  llm_enabled?: number;
  llm_base_url?: string;
  llm_model?: string;
  llm_api_key_encrypted?: string;
  llm_updated_at?: string;
}

function credentialKey(): Buffer {
  const secret =
    process.env.MAIL_CREDENTIAL_KEY
    || process.env.JWT_SECRET
    || 'local-llm-credential-key';
  return createHash('sha256').update(secret).digest();
}

export function encryptLlmApiKey(value: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', credentialKey(), iv);
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${iv.toString('base64')}.${tag.toString('base64')}.${encrypted.toString('base64')}`;
}

export function decryptLlmApiKey(value: unknown): string {
  try {
    const [ivText, tagText, encryptedText] = String(value || '').split('.');
    if (!ivText || !tagText || !encryptedText) return '';
    const decipher = createDecipheriv('aes-256-gcm', credentialKey(), Buffer.from(ivText, 'base64'));
    decipher.setAuthTag(Buffer.from(tagText, 'base64'));
    return Buffer.concat([
      decipher.update(Buffer.from(encryptedText, 'base64')),
      decipher.final(),
    ]).toString('utf8');
  } catch {
    return '';
  }
}

function rowFor(userId: number): UserSettingsRow | undefined {
  return getDb()
    .prepare('SELECT llm_enabled, llm_base_url, llm_model, llm_api_key_encrypted, llm_updated_at FROM user_settings WHERE user_id=?')
    .get(userId) as UserSettingsRow | undefined;
}

export function getLlmApiSettings(userId: number, includeSecret = false): LlmApiSettings {
  const row = rowFor(userId);
  const encrypted = row?.llm_api_key_encrypted || '';
  const apiKey = includeSecret ? decryptLlmApiKey(encrypted) : undefined;
  return {
    enabled: Boolean(row?.llm_enabled),
    baseUrl: String(row?.llm_base_url || '').trim(),
    model: String(row?.llm_model || '').trim(),
    apiKeySaved: Boolean(encrypted),
    ...(includeSecret ? { apiKey } : {}),
    updatedAt: row?.llm_updated_at,
  };
}

export function saveLlmApiSettings(
  userId: number,
  input: {
    enabled?: boolean;
    baseUrl?: string;
    model?: string;
    apiKey?: string;
    removeKey?: boolean;
  },
): LlmApiSettings {
  const current = rowFor(userId);
  const encrypted = current?.llm_api_key_encrypted || '';
  const enabled = input.enabled ?? Boolean(current?.llm_enabled);
  const baseUrl = input.baseUrl !== undefined ? String(input.baseUrl || '').trim() : String(current?.llm_base_url || '').trim();
  const model = input.model !== undefined ? String(input.model || '').trim() : String(current?.llm_model || '').trim();
  const nextEncrypted =
    input.removeKey ? '' :
    (typeof input.apiKey === 'string' && input.apiKey.trim() ? encryptLlmApiKey(input.apiKey.trim()) : encrypted);
  getDb().prepare('INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)').run(userId);
  getDb().prepare(`
    UPDATE user_settings
    SET llm_enabled=?, llm_base_url=?, llm_model=?, llm_api_key_encrypted=?, llm_updated_at=datetime('now','localtime')
    WHERE user_id=?
  `).run(
    enabled ? 1 : 0,
    baseUrl,
    model,
    nextEncrypted,
    userId,
  );
  return getLlmApiSettings(userId);
}

/** Build per-user provider overrides for A-side runs (empty when disabled). */
export function llmOverridesForUser(userId: number): LlmProviderOverrides | null {
  const settings = getLlmApiSettings(userId, true);
  if (!settings.enabled || !settings.baseUrl || !settings.model || !settings.apiKey) return null;
  return {
    llm_api_key: settings.apiKey,
    llm_base_url: settings.baseUrl,
    llm_model: settings.model,
  };
}

/** Mutate a D->A payload with this user's provider overrides. */
export function attachLlmOverrides<T extends Record<string, unknown>>(
  body: T,
  userId?: number | string | null,
): T {
  const id = Number(userId);
  if (!Number.isFinite(id) || id <= 0) return body;
  const overrides = llmOverridesForUser(id);
  if (overrides) Object.assign(body, overrides);
  return body;
}
