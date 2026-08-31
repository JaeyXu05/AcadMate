import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Input, App, Button, Empty, Spin } from 'antd';
import axios from 'axios';
import { Mail, Copy, Zap, Send, Inbox, RotateCw } from 'lucide-react';
import * as userApi from '../services/user';
import { getAdvisorDetail } from '../services/advisor';
import { generateEmail, getEmailInbox, getEmailOutbox, getEmailStatus, sendEmail } from '../services/email';
import type { AdvisorDetail } from '../types/advisor';
import PageCloseButton from '../components/PageCloseButton';
import styles from './EmailPage.module.css';

const { TextArea } = Input;

function mailLabel(status: { configured: boolean; reachable: boolean | null; message: string } | null): string {
  if (!status) return '检测中';
  if (!status.configured) return '未配置';
  if (status.reachable === true) return '通';
  if (status.reachable === false) return '不通';
  return status.message || '未配置';
}

function EmailPage() {
  const [searchParams] = useSearchParams();
  const { message } = App.useApp();

  const [advisors, setAdvisors] = useState<AdvisorDetail[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [mailboxLoading, setMailboxLoading] = useState(false);
  const [smtpStatus, setSmtpStatus] = useState<{ configured: boolean; reachable: boolean | null; message: string } | null>(null);
  const [imapStatus, setImapStatus] = useState<{ configured: boolean; reachable: boolean | null; message: string } | null>(null);
  const [outbox, setOutbox] = useState<Array<Record<string, any>>>([]);
  const [inbox, setInbox] = useState<Array<{ uid: number; from: string; subject: string; date?: string; text: string }>>([]);

  // 加载收藏夹导师列表（取详情用于展示姓名/院系）。
  // 若 URL 预选了 advisor_id 但该导师不在收藏夹，仍单独拉取并入列表，
  // 因为后端邮件生成不依赖收藏——避免"给非收藏导师写信"静默失效。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingList(true);
      try {
        const presetId = searchParams.get('advisor_id');
        const favs = await userApi.getFavorites();
        const favDetails = await Promise.all(
          favs.map((f) => getAdvisorDetail(f.advisor_id).catch(() => null)),
        );
        let valid = favDetails.filter((d): d is AdvisorDetail => d !== null);

        // 预选导师若不在收藏列表，单独拉取并入
        if (presetId && !valid.some((a) => a.id === presetId)) {
          const extra = await getAdvisorDetail(presetId).catch(() => null);
          if (extra) valid = [extra, ...valid];
        }

        if (!cancelled) {
          setAdvisors(valid);
          if (presetId && valid.some((a) => a.id === presetId)) {
            setSelectedId(presetId);
          }
        }
      } catch {
        if (!cancelled) message.error('加载导师列表失败');
      } finally {
        if (!cancelled) setLoadingList(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleGenerate = async () => {
    if (!selectedId) return;
    setGenerating(true);
    try {
      const draft = await generateEmail(selectedId);
      setSubject(draft.subject);
      setBody(draft.body);
      message.success('邮件已生成，可按需编辑后复制');
    } catch (error: unknown) {
      const serverMessage = axios.isAxiosError(error)
        && typeof error.response?.data?.message === 'string'
        ? error.response.data.message
        : null;
      message.error(serverMessage ?? '生成邮件失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async () => {
    const text = `主题：${subject}\n\n${body}`;
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制到剪贴板');
    } catch {
      message.error('复制失败，请手动选择文本复制');
    }
  };

  const handleSend = async () => {
    if (!selectedId || !subject.trim() || !body.trim()) return;
    setSending(true);
    try {
      const result = await sendEmail(selectedId, subject, body);
      const sent = result.item?.status === 'sent';
      setSmtpStatus((current) => ({
        configured: Boolean(result.smtp_configured),
        reachable: sent ? true : (current?.reachable ?? null),
        message: sent ? '通' : (result.smtp_configured ? '已配置' : '未配置'),
      }));
      if (sent) message.success('邮件已发送');
      else if (!result.smtp_configured) message.success('邮件已进入待发送队列；SMTP 未配置，不会伪装成已发送');
      else message.warning(result.item?.error || '邮件未发出，请查看发件记录');
      await loadMailbox(false);
    } catch (error: unknown) {
      const text = axios.isAxiosError(error) && typeof error.response?.data?.message === 'string'
        ? error.response.data.message : '邮件发送失败';
      message.error(text);
    } finally { setSending(false); }
  };

  const loadMailbox = async (includeInbox = true) => {
    setMailboxLoading(true);
    try {
      const sent = await getEmailOutbox();
      setOutbox(sent.items);
      setSmtpStatus((current) => current ?? {
        configured: Boolean(sent.smtp_configured),
        reachable: null,
        message: sent.smtp_configured ? '已配置' : '未配置',
      });
      if (includeInbox) {
        try {
          const received = await getEmailInbox();
          setInbox(received.items);
          setImapStatus((current) => ({
            configured: Boolean(received.imap_configured),
            reachable: received.imap_configured ? true : null,
            message: received.imap_configured ? '通' : '未配置',
          }));
        } catch (error: unknown) {
          const text = axios.isAxiosError(error) && typeof error.response?.data?.message === 'string'
            ? error.response.data.message : '收件箱读取失败';
          message.warning(text);
        }
      }
    } finally { setMailboxLoading(false); }
  };

  const probeMail = async () => {
    try {
      const status = await getEmailStatus();
      setSmtpStatus(status.smtp);
      setImapStatus(status.imap);
    } catch {
      setSmtpStatus({ configured: false, reachable: null, message: '未配置' });
      setImapStatus({ configured: false, reachable: null, message: '未配置' });
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await probeMail();
      if (!cancelled) await loadMailbox(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const selectedAdvisor = advisors.find((a) => a.id === selectedId);

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <Mail size={16} strokeWidth={1.5} className="text-slate-600" />
        邮件模板
      </h2>
      <p className={styles.subtitle}>生成有证据约束的联系草稿，可编辑、发送并核查发件状态；邮箱服务未配置时不会伪装成已发送。</p>

      <div className={styles.body}>
        {/* 左：导师选择 */}
        <div className={styles.picker}>
          <div className={styles.pickerHeader}>
            {loadingList ? '加载中…' : `共 ${advisors.length} 位收藏导师`}
          </div>
          <div className={styles.pickerList}>
            {!loadingList && advisors.length === 0 ? (
              <div className={styles.pickerEmpty}>
                收藏夹为空，请先在检索页收藏导师
              </div>
            ) : (
              advisors.map((a) => (
                <div
                  key={a.id}
                  className={`${styles.pickerItem} ${a.id === selectedId ? styles.pickerItemActive : ''}`}
                  onClick={() => setSelectedId(a.id)}
                >
                  <div className={styles.pickerAvatar}>{a.name.charAt(0)}</div>
                  <div>
                    <div className={styles.pickerName}>{a.name}</div>
                    <div className={styles.pickerDept}>{a.department}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* 右：邮件编辑 */}
        <div className={styles.editor}>
          <div className={styles.editorHeader}>
            <span className={styles.editorHint}>
              {selectedAdvisor ? `收件人：${selectedAdvisor.name}（${selectedAdvisor.department}）` : '请先选择导师'}
            </span>
            <button
              className={styles.generateBtn}
              onClick={handleGenerate}
              disabled={!selectedId || generating}
            >
              <Zap size={14} strokeWidth={1.5} className="text-slate-600" />
              {generating ? '生成中…' : '生成邮件'}
            </button>
          </div>

          {subject || body ? (
            <>
              <div className={styles.editorBody}>
                <Input
                  className={`${styles.subjectInput} input-quiet`}
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="邮件主题"
                  size="large"
                />
                <TextArea
                  className={`${styles.bodyInput} input-quiet`}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="邮件正文"
                  autoSize={{ minRows: 12 }}
                />
              </div>
              <div className={styles.editorFooter}>
                <button
                  className={styles.copyBtn}
                  onClick={handleCopy}
                  disabled={!subject && !body}
                >
                  <Copy size={14} strokeWidth={1.5} className="text-slate-600" />
                  一键复制
                </button>
                <button className={styles.copyBtn} onClick={handleSend} disabled={!selectedId || !subject.trim() || !body.trim() || sending}>
                  <Send size={14} strokeWidth={1.5} className="text-slate-600" />
                  {sending ? '发送中…' : '确认发送'}
                </button>
              </div>
            </>
          ) : (
            <div className={styles.placeholder}>
              <Mail size={28} strokeWidth={1.5} className="text-slate-300" />
              <span>选择导师后点击「生成邮件」</span>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 28, borderTop: '1px solid rgba(28,25,23,.08)', paddingTop: 22 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
          <div>
            <h3 style={{ color: '#1c1917', margin: 0, fontWeight: 500 }} className="inline-flex items-center gap-2"><Inbox size={16} strokeWidth={1.5} className="text-slate-600" /> 邮件收发记录</h3>
            <div style={{ color: '#a8a29e', marginTop: 5, fontSize: 12 }}>
              SMTP：{mailLabel(smtpStatus)} · IMAP：{mailLabel(imapStatus)}
            </div>
          </div>
          <Button icon={<RotateCw size={14} strokeWidth={1.5} className="text-slate-600" />} loading={mailboxLoading} onClick={() => void Promise.all([probeMail(), loadMailbox(true)])}>刷新邮箱</Button>
        </div>
        {mailboxLoading ? <div style={{ minHeight: 100, display: 'grid', placeItems: 'center' }}><Spin /></div> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
            <section style={{ background: '#fff', border: '1px solid rgba(28,25,23,.08)', padding: 16 }}>
              <h4 style={{ color: '#1c1917', marginTop: 0, fontWeight: 500 }}>发件箱</h4>
              {!outbox.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无发件记录" /> : outbox.slice(0, 20).map((item) => (
                <div key={item.id} style={{ borderTop: '1px solid rgba(28,25,23,.06)', padding: '10px 0', color: '#44403c' }}>
                  <div>{String(item.subject || '')}</div><small>{String(item.recipient || '')} · {String(item.status || '')}</small>
                </div>
              ))}
            </section>
            <section style={{ background: '#fff', border: '1px solid rgba(28,25,23,.08)', padding: 16 }}>
              <h4 style={{ color: '#1c1917', marginTop: 0, fontWeight: 500 }}>收件箱</h4>
              {!inbox.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={imapStatus && !imapStatus.configured ? 'IMAP 未配置' : '暂无邮件'} /> : inbox.map((item) => (
                <div key={item.uid} style={{ borderTop: '1px solid rgba(28,25,23,.06)', padding: '10px 0', color: '#44403c' }}>
                  <div>{item.subject}</div><small>{item.from} · {item.date || ''}</small>
                  {item.text && <div style={{ color: '#a8a29e', fontSize: 12, marginTop: 4 }}>{item.text.slice(0, 180)}</div>}
                </div>
              ))}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

export default EmailPage;
