import api from './axios';

export interface IntegrationAccount { id: number; provider: string; external_user_id?: string | null; status: string; config?: Record<string, unknown>; last_sync_at?: string | null; last_error?: string | null; }
export interface ZoteroCollection { id: string; name: string; parent?: string | null; item_count?: number | null; }
export async function listIntegrations(): Promise<IntegrationAccount[]> { return (await api.get('/integrations')).data; }
export async function connectZotero(library_id: string, api_key: string): Promise<IntegrationAccount> { return (await api.post('/integrations/zotero/connect', { library_id, api_key }, { timeout: 20000 })).data; }
export async function listZoteroCollections(): Promise<ZoteroCollection[]> { return (await api.get('/integrations/zotero/collections', { timeout: 20000 })).data; }
export async function syncZotero(collection_id?: string): Promise<{ imported: number; synced_at: string }> { return (await api.post('/integrations/zotero/sync', { collection_id }, { timeout: 30000 })).data; }
export async function disconnectZotero(): Promise<void> { await api.delete('/integrations/zotero'); }

