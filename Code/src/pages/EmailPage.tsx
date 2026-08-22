import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Input, App } from 'antd';
import { MailOutlined, CopyOutlined, ThunderboltOutlined } from '@ant-design/icons';
import * as userApi from '../services/user';
import { getAdvisorDetail } from '../services/advisor';
import { generateEmail } from '../services/email';
import type { AdvisorDetail } from '../types/advisor';
import PageCloseButton from '../components/PageCloseButton';
import styles from './EmailPage.module.css';

const { TextArea } = Input;

function EmailPage() {
  const [searchParams] = useSearchParams();
  const { message } = App.useApp();

  const [advisors, setAdvisors] = useState<AdvisorDetail[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [generating, setGenerating] = useState(false);

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
    } catch {
      message.error('生成邮件失败');
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

  const selectedAdvisor = advisors.find((a) => a.id === selectedId);

  return (
    <div className={styles.container}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <MailOutlined style={{ color: '#667eea' }} />
        邮件模板
      </h2>
      <p className={styles.subtitle}>选择一位导师，一键生成联系邮件草稿，可编辑后复制使用</p>

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
              <ThunderboltOutlined />
              {generating ? '生成中…' : '生成邮件'}
            </button>
          </div>

          {subject || body ? (
            <>
              <div className={styles.editorBody}>
                <Input
                  className={styles.subjectInput}
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="邮件主题"
                  size="large"
                />
                <TextArea
                  className={styles.bodyInput}
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
                  <CopyOutlined />
                  一键复制
                </button>
              </div>
            </>
          ) : (
            <div className={styles.placeholder}>
              <MailOutlined style={{ fontSize: 40, opacity: 0.4 }} />
              <span>选择导师后点击「生成邮件」</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default EmailPage;
