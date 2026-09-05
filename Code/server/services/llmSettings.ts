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

const UNSAFE_CREDENTIAL_SECRETS = new Set([
  '',
  'replace-with-a-long-random-secret',
  'dev-secret-change-me',
  'secret',
  'changeme',
  'change-me',
  'your-secret-key',
]);

function configuredCredentialSecret(value: unknown): string {
  const text = String(value ?? '').trim();
  return text.length >= 16 && !UNSAFE_CREDENTIAL_SECRETS.has(text.toLowerCase()) ? text : '';
}

function credentialKey(): Buffer {
  const secret =
    configuredCredentialSecret(process.env.MAIL_CREDENTIAL_KEY)
    || configuredCredentialSecret(process.env.JWT_SECRET);
  if (!secret) {
    throw new Error('缺少安全的本地凭据加密密钥，请重新启动服务以生成 JWT_SECRET');
  }
  return createHash('sha256').update(secret).digest();
}

function decryptWithKey(value: string, key: Buffer): string {
  const [ivText, tagText, encryptedText] = value.split('.');
  if (!ivText || !tagText || !encryptedText) return '';
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(ivText, 'base64'));
  decipher.setAuthTag(Buffer.from(tagText, 'base64'));
  return Buffer.concat([
    decipher.update(Buffer.from(encryptedText, 'base64')),
    decipher.final(),
  ]).toString('utf8');
}

export function encryptLlmApiKey(value: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', credentialKey(), iv);
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${iv.toString('base64')}.${tag.toString('base64')}.${encrypted.toString('base64')}`;
}

function decryptLlmApiKeyResult(value: unknown): { apiKey: string; legacy: boolean } {
  const encrypted = String(value || '');
  try {
    return { apiKey: decryptWithKey(encrypted, credentialKey()), legacy: false };
  } catch {
    // Compatibility for records created when the public .env.example value
    // was accidentally accepted as an encryption key. New writes never use it.
    try {
      return {
        apiKey: decryptWithKey(
          encrypted,
          createHash('sha256').update('replace-with-a-long-random-secret').digest(),
        ),
        legacy: true,
      };
    } catch { return { apiKey: '', legacy: false }; }
  }
}

export function decryptLlmApiKey(value: unknown): string {
  return decryptLlmApiKeyResult(value).apiKey;
}

function rowFor(userId: number): UserSettingsRow | undefined {
  return getDb()
    .prepare('SELECT llm_enabled, llm_base_url, llm_model, llm_api_key_encrypted, llm_updated_at FROM user_settings WHERE user_id=?')
    .get(userId) as UserSettingsRow | undefined;
}

export function getLlmApiSettings(userId: number, includeSecret = false): LlmApiSettings {
  const row = rowFor(userId);
  const encrypted = row?.llm_api_key_encrypted || '';
  const decrypted = includeSecret ? decryptLlmApiKeyResult(encrypted) : undefined;
  const apiKey = decrypted?.apiKey;
  if (decrypted?.legacy && apiKey) {
    getDb().prepare(
      "UPDATE user_settings SET llm_api_key_encrypted=?, llm_updated_at=datetime('now','localtime') WHERE user_id=?",
    ).run(encryptLlmApiKey(apiKey), userId);
  }
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

export const API_SETTINGS_REQUIRED_CODE = 'API_SETTINGS_REQUIRED';
export const API_SETTINGS_PATH = '/api-settings';

export function hasUsableLlmSettings(userId: number): boolean {
  return llmOverridesForUser(userId) !== null;
}

export function apiSettingsRequired(feature = '此功能') {
  return {
    code: API_SETTINGS_REQUIRED_CODE,
    message: `${feature}需要模型 API。请先为当前账号填写 API 地址、模型名称和 API Key。`,
    action: { label: '前往 API 设置', path: API_SETTINGS_PATH },
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
