import { useEffect, useState } from 'react';
import { Button, Empty, Input, Select, Spin, Tag, message } from 'antd';
import { BookMarked, Link2, RefreshCw, Unplug } from 'lucide-react';
import * as integrationsApi from '../services/integrations';
import type { IntegrationAccount, ZoteroCollection } from '../services/integrations';
import { apiErrorMessage } from '../services/axios';
import styles from './IntegrationsPage.module.css';

function IntegrationsPage() {
  const [account, setAccount] = useState<IntegrationAccount | null>(null);
  const [collections, setCollections] = useState<ZoteroCollection[]>([]);
  const [libraryId, setLibraryId] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [collection, setCollection] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const load = async () => { try { const items = await integrationsApi.listIntegrations(); setAccount(items.find((item) => item.provider === 'zotero') || null); } catch (error: unknown) { message.error(apiErrorMessage(error, '科研软件连接加载失败')); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  const connect = async () => { setWorking(true); try { const connected = await integrationsApi.connectZotero(libraryId, apiKey); setAccount(connected); setApiKey(''); message.success('Zotero 已连接'); } catch (error: unknown) { message.error(apiErrorMessage(error, 'Zotero 连接失败')); } finally { setWorking(false); } };
  const getCollections = async () => { setWorking(true); try { setCollections(await integrationsApi.listZoteroCollections()); message.success('Collection 已加载'); } catch (error: unknown) { message.error(apiErrorMessage(error, 'Collection 加载失败')); } finally { setWorking(false); } };
  const sync = async () => { setWorking(true); try { const result = await integrationsApi.syncZotero(collection); message.success(`已同步 ${result.imported} 条 Zotero 条目`); await load(); } catch (error: unknown) { message.error(apiErrorMessage(error, 'Zotero 同步失败')); } finally { setWorking(false); } };
  const disconnect = async () => { setWorking(true); try { await integrationsApi.disconnectZotero(); setAccount(null); setCollections([]); message.success('Zotero 已断开'); } catch (error: unknown) { message.error(apiErrorMessage(error, '断开失败')); } finally { setWorking(false); } };
  if (loading) return <div className={styles.loading}><Spin /></div>;
  return <div className={styles.page}><header className={styles.header}><div><div className={styles.kicker}>OTHER · CONNECTORS</div><h1>科研软件连接</h1><p>先连接 Zotero，再把文献库带入科研项目和对话。</p></div></header><section className={styles.card}><div className={styles.cardHead}><BookMarked size={20} /><div><h2>Zotero</h2><span>论文元数据、Collection 和笔记的增量同步</span></div>{account && <Tag color="green">已连接</Tag>}</div>{!account ? <div className={styles.form}><Input value={libraryId} onChange={(event) => setLibraryId(event.target.value)} placeholder="Library ID" /><Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Zotero API Key（只写入加密存储）" /><Button type="primary" icon={<Link2 size={14} />} loading={working} disabled={!libraryId.trim() || !apiKey.trim()} onClick={() => void connect()}>验证并连接</Button></div> : <><div className={styles.connected}>Library ID：{account.external_user_id}<span>{account.last_sync_at ? `上次同步：${account.last_sync_at}` : '尚未同步'}</span></div><div className={styles.actions}><Button icon={<RefreshCw size={14} />} loading={working} onClick={() => void getCollections()}>读取 Collection</Button><Button danger icon={<Unplug size={14} />} loading={working} onClick={() => void disconnect()}>断开连接</Button></div>{collections.length > 0 && <div className={styles.sync}><Select allowClear value={collection} onChange={setCollection} placeholder="选择 Collection（不选则同步整个库）" options={collections.map((item) => ({ label: `${item.name}${item.item_count == null ? '' : `（${item.item_count}）`}`, value: item.id }))} /><Button type="primary" loading={working} onClick={() => void sync()}>开始增量同步</Button></div>}{collections.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="先读取 Collection，再选择需要同步的范围" />}</>}</section></div>;
}

export default IntegrationsPage;

