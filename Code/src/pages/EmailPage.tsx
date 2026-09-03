import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Input, App, Button, Empty, Spin, Checkbox } from 'antd';
import axios from 'axios';
import { Mail, Copy, Zap, Send, Inbox, RotateCw, Save, X } from 'lucide-react';
import * as userApi from '../services/user';
import { getAdvisorDetail } from '../services/advisor';
import {
  generateEmail, getEmailInbox, getEmailOutbox, getEmailSettings, getEmailStatus,
  saveEmailSettings, sendEmailWithRecipients,
  type EmailSettings,
} from '../services/email';
import type { AdvisorDetail } from '../types/advisor';
import PageCloseButton from '../components/PageCloseButton';
import styles from './EmailPage.module.css';

const { TextArea } = Input;

const USTC_CLIENT_PASSWORD_PATTERN = /^[A-Za-z0-9]{16}$/;

function isUstcMailHost(value: string | undefined): boolean {
  return String(value || '').toLowerCase().includes('ustc.edu.cn');
}

function removeUstcPasswordSpaces(value: string): string {
  return value.replace(/\s+/g, '');
}

function isUstcPasswordFormat(value: string): boolean {
  return USTC_CLIENT_PASSWORD_PATTERN.test(removeUstcPasswordSpaces(value));
}

function normalizePasswordForHost(host: string | undefined, value: string): string {
  return isUstcMailHost(host) ? removeUstcPasswordSpaces(value) : value;
}

function mailLabel(status: { configured: boolean; reachable: boolean | null; message: string } | null): string {
  if (!status) return '检测中';
  if (!status.configured) return '未配置';
  if (status.reachable === true) return '通';
  if (status.reachable === false) return '不通';
  return status.message || '未配置';
}

function mailStatusTitle(status: { configured: boolean; reachable: boolean | null; message: string } | null): string {
  return status?.message || '检测中';
}

function EmailPage() {
  const [searchParams] = useSearchParams();
  const { message } = App.useApp();

  const [advisors, setAdvisors] = useState<AdvisorDetail[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [recipientText, setRecipientText] = useState('');
  const [mailSettings, setMailSettings] = useState<EmailSettings | null>(null);
  const [smtpPassword, setSmtpPassword] = useState('');
  const [imapPassword, setImapPassword] = useState('');
  const [smtpPasswordTouched, setSmtpPasswordTouched] = useState(false);
  const [imapPasswordTouched, setImapPasswordTouched] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [mailHelpOpen, setMailHelpOpen] = useState(false);
  const settingsFromMenu = searchParams.get('settings') === '1';
  const [showMailSettings, setShowMailSettings] = useState(() => {
    try { return window.localStorage.getItem('mail-settings-dismissed') !== '1'; } catch { return true; }
  });
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const [mailboxLoading, setMailboxLoading] = useState(false);
  const [smtpStatus, setSmtpStatus] = useState<{ configured: boolean; reachable: boolean | null; message: string } | null>(null);
  const [imapStatus, setImapStatus] = useState<{ configured: boolean; reachable: boolean | null; message: string } | null>(null);
  const [outbox, setOutbox] = useState<Array<Record<string, any>>>([]);
  const [inbox, setInbox] = useState<Array<{ uid: number; from: string; subject: string; date?: string; text: string }>>([]);
  const [activityWidth, setActivityWidth] = useState(() => {
    try {
      const saved = Number(window.localStorage.getItem('email-activity-width'));
      return Number.isFinite(saved) ? Math.min(520, Math.max(280, saved)) : 320;
    } catch { return 320; }
  });
  const bodyRef = useRef<HTMLDivElement>(null);
  const resizingActivity = useRef(false);

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
      if (draft.default_recipients?.length) setRecipientText(draft.default_recipients.join(', '));
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
    const recipients = recipientText
      .split(/[;,，；\s]+/)
      .map((item) => item.trim().toLowerCase())
      .filter((item, index, all) => item && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(item) && all.indexOf(item) === index);
    if (!recipients.length) {
      message.error('请填写至少一个有效收件人邮箱');
      return;
    }
    if (!smtpPassword && !mailSettings?.smtp_password_saved && !smtpStatus?.configured) {
      message.error('请先填写 SMTP 客户端专用密码；已保存密码时无需重复填写');
      return;
    }
    if (!window.confirm(`确认使用 ${mailSettings?.smtp_user || '当前 SMTP 账号'} 向以下地址发送吗？\n${recipients.join('\n')}`)) return;
    setSending(true);
    try {
      const result = await sendEmailWithRecipients(selectedId, recipients, subject, body, smtpPassword);
      const sent = Array.isArray(result.items)
        ? result.items.length === recipients.length && result.items.every((item: { status?: string }) => item.status === 'sent')
        : result.item?.status === 'sent';
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

  const updateMailSetting = <K extends keyof EmailSettings>(key: K, value: EmailSettings[K]) => {
    setMailSettings((current) => current ? { ...current, [key]: value } : current);
  };

  const changeSmtpPassword = (value: string) => {
    const cleaned = normalizePasswordForHost(mailSettings?.smtp_host, value);
    setSmtpPassword(cleaned);
    setSmtpPasswordTouched(true);
    if (cleaned && isUstcMailHost(mailSettings?.smtp_host) && !isUstcPasswordFormat(cleaned)) {
      setMailHelpOpen(true);
    }
  };

  const changeImapPassword = (value: string) => {
    const imapHost = mailSettings?.imap_same_as_smtp ? mailSettings.smtp_host : mailSettings?.imap_host;
    const cleaned = normalizePasswordForHost(imapHost, value);
    setImapPassword(cleaned);
    setImapPasswordTouched(true);
    if (cleaned && isUstcMailHost(imapHost) && !isUstcPasswordFormat(cleaned)) {
      setMailHelpOpen(true);
    }
  };

  const resizeActivity = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizingActivity.current || !bodyRef.current || window.innerWidth <= 820) return;
    const bodyRect = bodyRef.current.getBoundingClientRect();
    const nextWidth = Math.min(520, Math.max(280, bodyRect.right - event.clientX));
    setActivityWidth(nextWidth);
  };

  const startResizeActivity = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (window.innerWidth <= 820) return;
    event.preventDefault();
    resizingActivity.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const stopResizeActivity = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizingActivity.current) return;
    resizingActivity.current = false;
    try { window.localStorage.setItem('email-activity-width', String(Math.round(activityWidth))); } catch { /* 无法使用本地存储时仅保持本次 */ }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const smtpPasswordFormatError = mailSettings
    && isUstcMailHost(mailSettings.smtp_host)
    && smtpPassword
    && !isUstcPasswordFormat(smtpPassword)
    ? 'USTC 客户端专用密码应为 16 位字母或数字（不含空格），请查看上方“如何填写邮箱设置？”'
    : '';
  const imapHostValue = mailSettings?.imap_same_as_smtp ? mailSettings.smtp_host : mailSettings?.imap_host;
  const imapPasswordFormatError = mailSettings
    && isUstcMailHost(imapHostValue)
    && imapPassword
    && !isUstcPasswordFormat(imapPassword)
    ? 'USTC 客户端专用密码应为 16 位字母或数字（不含空格），请查看上方“如何填写邮箱设置？”'
    : '';

  const handleSaveMailSettings = async () => {
    if (!mailSettings) return;
    if (smtpPasswordFormatError || imapPasswordFormatError) {
      setMailHelpOpen(true);
      message.error('USTC 客户端专用密码格式不正确，请查看上方“如何填写邮箱设置？”');
      return;
    }
    setSettingsSaving(true);
    try {
      // 未手动改动过的旧密码在“记住密码”取消时传空，服务端才会真正删除；
      // 手动输入过的新密码始终提交，由服务端按既有规则加密保存。
      const smtpPasswordToSave = smtpPasswordTouched || mailSettings.remember_smtp_password ? smtpPassword : '';
      const imapPasswordToSave = mailSettings.imap_same_as_smtp
        ? smtpPasswordToSave
        : (imapPasswordTouched || mailSettings.remember_imap_password ? imapPassword : '');
      const saved = await saveEmailSettings({
        ...mailSettings,
        smtp_password: smtpPasswordToSave,
        imap_password: imapPasswordToSave,
      });
      setMailSettings(saved);
      setSmtpPassword(normalizePasswordForHost(saved.smtp_host, saved.smtp_password_value || ''));
      setImapPassword(normalizePasswordForHost(
        saved.imap_same_as_smtp ? saved.smtp_host : saved.imap_host,
        saved.imap_password_value || '',
      ));
      setSmtpPasswordTouched(false);
      setImapPasswordTouched(false);
      message.success('邮箱设置已保存；密码已加密保存');
      await probeMail();
    } catch (error: unknown) {
      const text = axios.isAxiosError(error) && typeof error.response?.data?.message === 'string'
        ? error.response.data.message : '邮箱设置保存失败';
      message.error(text);
    } finally { setSettingsSaving(false); }
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
      const received = await getEmailInbox(mailSettings?.imap_same_as_smtp ? smtpPassword : imapPassword);
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
      const status = await getEmailStatus(
        smtpPassword,
        mailSettings?.imap_same_as_smtp ? smtpPassword : imapPassword,
      );
      setSmtpStatus(status.smtp);
      setImapStatus(status.imap);
    } catch {
      setSmtpStatus({ configured: false, reachable: null, message: '未配置' });
      setImapStatus({ configured: false, reachable: null, message: '未配置' });
    }
  };

  useEffect(() => {
    if (settingsFromMenu) setShowMailSettings(true);
  }, [settingsFromMenu]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const settings = await getEmailSettings();
        if (!cancelled) {
          setMailSettings(settings);
          setSmtpPassword(normalizePasswordForHost(settings.smtp_host, settings.smtp_password_value || ''));
          setImapPassword(normalizePasswordForHost(
            settings.imap_same_as_smtp ? settings.smtp_host : settings.imap_host,
            settings.imap_password_value || '',
          ));
          setSmtpPasswordTouched(false);
          setImapPasswordTouched(false);
        }
      } catch {
        if (!cancelled) message.warning('邮箱设置读取失败，请检查后端状态');
      }
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

      {mailSettings && showMailSettings && <div className={styles.mailSettings}>
        <div className={styles.mailSettingsHeader}>
          <div>
            <div className={styles.mailSettingsTitle}>邮箱发送设置</div>
            <div className={styles.mailSettingsHint}>SMTP 用于发送邮件；IMAP 用于收到的回复。</div>
            <details
              className={styles.mailHelp}
              open={mailHelpOpen}
              onToggle={(event) => setMailHelpOpen((event.target as HTMLDetailsElement).open)}
            >
              <summary>如何填写邮箱设置？</summary>
              <div className={styles.mailHelpBody}>
                <div>中国科大邮箱：SMTP 和 IMAP 主机均填写 mail.ustc.edu.cn；SMTP 端口 465 并开启 SSL/TLS，IMAP 端口 993 并开启 SSL/TLS；账号填写完整邮箱地址，发件人显示地址通常与账号相同。</div>
                <div>客户端专用密码：登录邮箱网页后进入“设置 → 安全设置 → 客户端专用密码”，生成的是 16 位字母或数字（不含空格，界面上显示时按 4 位一组分隔）。直接粘贴或手动输入到本页即可，页面会自动去掉空格；请勿填写网页登录密码，并注意大小写。</div>
                <div>IMAP：用于读取收到的回复；主机、端口、账号和密码按邮箱服务商说明填写。若与 SMTP 是同一个邮箱，可勾选“与SMTP一致”；导师邮箱只填写在邮件编辑区的收件人栏。</div>
                <a href="https://mail.ustc.edu.cn/coremail/help/clientoption.jsp?locale=zh_CN" target="_blank" rel="noreferrer">查看中国科大官方客户端设置说明</a>
              </div>
            </details>
          </div>
          <div className={styles.mailSettingsActions}>
            <Button icon={<Save size={14} />} loading={settingsSaving} onClick={() => void handleSaveMailSettings()}>保存邮箱设置</Button>
            <button className={styles.closeSettingsBtn} aria-label="关闭邮箱设置" title="关闭" onClick={() => {
              setShowMailSettings(false);
              try { window.localStorage.setItem('mail-settings-dismissed', '1'); } catch { /* 无法使用本地存储时仅关闭本次 */ }
            }}><X size={16} /></button>
          </div>
        </div>
        <div className={styles.mailSettingsSection}>
          <div className={styles.mailSectionTitle}>发送端 SMTP</div>
          <div className={styles.mailSettingsGrid}>
            <div className={styles.mailFieldRow}>
              <label>SMTP 主机<Input value={mailSettings.smtp_host} onChange={(e) => updateMailSetting('smtp_host', e.target.value)} placeholder="请输入 SMTP 主机" /></label>
              <label className={styles.portField}>端口（SSL 465）<Input type="number" value={mailSettings.smtp_port} onChange={(e) => updateMailSetting('smtp_port', Number(e.target.value))} /></label>
              <label className={styles.checkboxLine}><Checkbox checked={mailSettings.smtp_secure} onChange={(e) => updateMailSetting('smtp_secure', e.target.checked)} />SSL/TLS</label>
            </div>
            <div className={`${styles.mailFieldRow} ${styles.threeColumns}`}>
              <label>SMTP 账号<Input value={mailSettings.smtp_user} onChange={(e) => updateMailSetting('smtp_user', e.target.value)} placeholder="完整邮箱地址" /></label>
              <label>发件人显示地址<Input value={mailSettings.smtp_from} onChange={(e) => updateMailSetting('smtp_from', e.target.value)} placeholder="通常与 SMTP 账号相同" /></label>
              <label>客户端专用密码 {mailSettings.smtp_password_saved && <span className={styles.savedMark}>已保存</span>}
                <Input.Password
                  name="smtp-client-password"
                  autoComplete="new-password"
                  data-lpignore="true"
                  value={smtpPassword}
                  placeholder="请输入客户端专用密码"
                  onChange={(e) => changeSmtpPassword(e.target.value)}
                />
                {smtpPasswordFormatError && <span className={styles.passwordFormatError} role="alert">{smtpPasswordFormatError}</span>}
              </label>
            </div>
            <label className={styles.checkboxLine}><Checkbox checked={mailSettings.remember_smtp_password} onChange={(e) => updateMailSetting('remember_smtp_password', e.target.checked)} />记住 SMTP 密码</label>
          </div>
        </div>
        <div className={styles.mailSettingsSection}>
          <div className={styles.mailSectionTitle}>接收端 IMAP</div>
          <div className={styles.mailSettingsGrid}>
            <label className={styles.sameAsSmtpLine}>
              <Checkbox checked={mailSettings.imap_same_as_smtp} onChange={(e) => updateMailSetting('imap_same_as_smtp', e.target.checked)} />
              与SMTP一致
            </label>
            <div className={styles.mailOptionsRow}>勾选后自动复用 SMTP 的主机、账号和密码；IMAP 端口与 SSL/TLS 仍按下方设置。</div>
            <div className={styles.mailFieldRow}>
              <label>IMAP 主机<Input value={mailSettings.imap_same_as_smtp ? mailSettings.smtp_host : mailSettings.imap_host} disabled={mailSettings.imap_same_as_smtp} onChange={(e) => updateMailSetting('imap_host', e.target.value)} placeholder="请输入 IMAP 主机" /></label>
              <label className={styles.portField}>端口（SSL 993）<Input type="number" value={mailSettings.imap_port} onChange={(e) => updateMailSetting('imap_port', Number(e.target.value))} /></label>
              <label className={styles.checkboxLine}><Checkbox checked={mailSettings.imap_secure} onChange={(e) => updateMailSetting('imap_secure', e.target.checked)} />SSL/TLS</label>
            </div>
            <div className={`${styles.mailFieldRow} ${styles.threeColumns}`}>
              <label>IMAP 账号<Input value={mailSettings.imap_same_as_smtp ? mailSettings.smtp_user : mailSettings.imap_user} disabled={mailSettings.imap_same_as_smtp} onChange={(e) => updateMailSetting('imap_user', e.target.value)} placeholder="完整邮箱地址" /></label>
              <label>IMAP 文件夹<Input value={mailSettings.imap_mailbox} onChange={(e) => updateMailSetting('imap_mailbox', e.target.value)} /></label>
              {mailSettings.imap_same_as_smtp ? (
                <label>IMAP 密码 {mailSettings.imap_password_saved && <span className={styles.savedMark}>已同步</span>}<div className={styles.mailReadonlyValue}>与 SMTP 密码相同（自动使用）</div></label>
              ) : (
                <label>IMAP 客户端专用密码 {mailSettings.imap_password_saved && <span className={styles.savedMark}>已保存</span>}
                  <Input.Password
                    name="imap-client-password"
                    autoComplete="new-password"
                    data-lpignore="true"
                    value={imapPassword}
                    placeholder="请输入客户端专用密码"
                    onChange={(e) => changeImapPassword(e.target.value)}
                  />
                  {imapPasswordFormatError && <span className={styles.passwordFormatError} role="alert">{imapPasswordFormatError}</span>}
                </label>
              )}
            </div>
            {!mailSettings.imap_same_as_smtp && <label className={styles.checkboxLine}><Checkbox checked={mailSettings.remember_imap_password} onChange={(e) => updateMailSetting('remember_imap_password', e.target.checked)} />记住 IMAP 密码</label>}
          </div>
        </div>
      </div>}

      {!showMailSettings && <div ref={bodyRef} className={`${styles.body} ${resizingActivity.current ? styles.isResizing : ''}`}>
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
                  value={recipientText}
                  onChange={(e) => setRecipientText(e.target.value)}
                  placeholder="收件人邮箱，可填写多个并用逗号或分号分隔"
                  size="large"
                />
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

        <div
          className={styles.resizeHandle}
          role="separator"
          aria-label="调整邮件模板和收发记录宽度"
          title="拖动调整邮件模板和收发记录宽度"
          onPointerDown={startResizeActivity}
          onPointerMove={resizeActivity}
          onPointerUp={stopResizeActivity}
          onPointerCancel={stopResizeActivity}
        >
          <span />
        </div>
        <aside className={styles.activity} style={{ flexBasis: `${activityWidth}px` }}>
          <div className={styles.activityHeader}>
            <div>
              <h3 className={styles.activityTitle}><Inbox size={16} strokeWidth={1.5} className="text-slate-600" /> 邮件收发记录</h3>
              <div className={styles.activityStatus} title={`SMTP：${mailStatusTitle(smtpStatus)}\nIMAP：${mailStatusTitle(imapStatus)}`}>SMTP：{mailLabel(smtpStatus)} · IMAP：{mailLabel(imapStatus)}</div>
            </div>
            <Button size="small" icon={<RotateCw size={14} strokeWidth={1.5} className="text-slate-600" />} loading={mailboxLoading} onClick={() => void Promise.all([probeMail(), loadMailbox(true)])}>刷新</Button>
          </div>
          {mailboxLoading ? <div className={styles.activityLoading}><Spin /></div> : (
            <div className={styles.activityScroll}>
              <section className={styles.activitySection}>
                <h4>发件箱</h4>
                {!outbox.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无发件记录" /> : outbox.slice(0, 50).map((item) => (
                  <div key={item.id} className={styles.activityItem}>
                    <div>{String(item.subject || '')}</div><small>{String(item.recipient || '')} · {String(item.status || '')}</small>
                  </div>
                ))}
              </section>
              <section className={styles.activitySection}>
                <h4>收件箱</h4>
                {!inbox.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={imapStatus && !imapStatus.configured ? 'IMAP 未配置' : '暂无邮件'} /> : inbox.map((item) => (
                  <div key={item.uid} className={styles.activityItem}>
                    <div>{item.subject}</div><small>{item.from} · {item.date || ''}</small>
                    {item.text && <div className={styles.activityPreview}>{item.text.slice(0, 180)}</div>}
                  </div>
                ))}
              </section>
            </div>
          )}
        </aside>
      </div>}
    </div>
  );
}

export default EmailPage;
