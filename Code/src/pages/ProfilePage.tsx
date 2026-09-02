import { useEffect, useState } from 'react';
import { Form, Input, Select, Card, App, Empty, Tag, Spin } from 'antd';
import { User, Mail, BookOpen, Users, Sparkles, ShieldCheck, AlertTriangle, Target } from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { emptyGrowth, generateResearchProfile, getGrowth, getResearchProfile } from '../services/user';
import type { ResearchProfile, ResearchCapabilityLevel } from '../services/user';
import type { GrowthState } from '../types/auth';
import PageCloseButton from '../components/PageCloseButton';
import Button from '../components/Button';
import { apiErrorMessage } from '../services/axios';
import styles from './ProfilePage.module.css';

const { TextArea } = Input;

/** 年级选项 */
const GRADE_OPTIONS = [
  '大一', '大二', '大三', '大四',
  '研一', '研二', '研三',
  '博一', '博二', '博三', '博四', '博五',
  '已毕业', '其他',
];

const LEVEL_LABELS: Record<ResearchCapabilityLevel, string> = {
  seen: '接触过',
  understood: '理解',
  implemented: '实现过',
  reproduced: '复现过',
  debugged: '调试过',
  experimented: '实验验证过',
  innovated: '形成创新',
  unknown: '证据不足',
};

function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [growth, setGrowth] = useState<GrowthState>(emptyGrowth());
  const [researchProfile, setResearchProfile] = useState<ResearchProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileGenerating, setProfileGenerating] = useState(false);
  const [profileStale, setProfileStale] = useState(false);
  const { message } = App.useApp();

  useEffect(() => {
    getGrowth()
      .then(setGrowth)
      .catch(() => setGrowth(emptyGrowth()));
    getResearchProfile()
      .then((result) => {
        setResearchProfile(result.profile);
        setProfileStale(result.stale);
      })
      .catch(() => {
        setResearchProfile(null);
        setProfileStale(false);
      })
      .finally(() => setProfileLoading(false));
  }, []);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await updateProfile({
        nickname: values.nickname,
        grade: values.grade,
        major: values.major,
        interests: values.interests || [],
        skills: values.skills || [],
        bio: values.bio,
      });
      message.success('个人信息已保存');
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) {
        // 表单校验错误，不做处理
        return;
      }
      const msg = err instanceof Error ? err.message : '保存失败，请重试';
      message.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateProfile = async () => {
    setProfileGenerating(true);
    try {
      const result = await generateResearchProfile();
      setResearchProfile(result.profile);
      setProfileStale(result.stale);
      message.success('科研画像已由模型更新');
    } catch (err: unknown) {
      message.error(apiErrorMessage(err, '科研画像生成失败，请稍后重试'));
    } finally {
      setProfileGenerating(false);
    }
  };

  const email = user?.email || '';
  const displayName = user?.nickname || email || '未命名用户';

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />
      <div className="mb-8 flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full border border-slate-300 text-sm text-slate-700">
          1
        </span>
        <div>
          <h2 className="text-lg font-semibold text-slate-800">个人信息</h2>
          <div className="mt-0.5 text-sm text-slate-500">{displayName}</div>
        </div>
      </div>

      <Card className={`${styles.card} ${styles.identityCard}`}>
        <Form
          form={form}
          layout="vertical"
          requiredMark="optional"
          initialValues={{
            email: user?.email || '',
            nickname: user?.nickname || '',
            grade: user?.grade || undefined,
            major: user?.major || '',
            interests: user?.interests || [],
            skills: user?.skills || [],
            bio: user?.bio || '',
          }}
        >
          <div className={styles.formGrid}>
            <Form.Item name="email" label="邮箱">
              <Input
                className="input-quiet"
                prefix={<Mail size={14} strokeWidth={1.5} className="text-slate-600" />}
                disabled
                size="large"
              />
            </Form.Item>

            <Form.Item name="nickname" label="昵称">
              <Input
                className="input-quiet"
                prefix={<User size={14} strokeWidth={1.5} className="text-slate-600" />}
                placeholder="给自己取个昵称"
                size="large"
              />
            </Form.Item>

            <Form.Item name="grade" label="年级">
              <Select
                className="input-quiet"
                placeholder="选择年级"
                options={GRADE_OPTIONS.map((g) => ({ label: g, value: g }))}
                size="large"
              />
            </Form.Item>

            <Form.Item name="major" label="专业 / 院系">
              <Input
                className="input-quiet"
                prefix={<Users size={14} strokeWidth={1.5} className="text-slate-600" />}
                placeholder="如：计算机科学与技术学院"
                size="large"
              />
            </Form.Item>

            <Form.Item name="interests" label="研究方向" className={styles.formFull}>
              <Select
                className="input-quiet"
                mode="tags"
                placeholder="输入后按回车添加，如：计算机视觉、深度学习"
                size="large"
              />
            </Form.Item>

            <Form.Item name="skills" label="已有技能" className={styles.formFull}>
              <Select
                className="input-quiet"
                mode="tags"
                placeholder="输入后按回车添加，如：Python、PyTorch"
                size="large"
              />
            </Form.Item>

            <Form.Item name="bio" label="个人简介" className={styles.formFull}>
              <TextArea
                className="input-quiet"
                placeholder="简单介绍一下自己（选填）"
                rows={4}
                maxLength={500}
                showCount
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }} className={styles.formFull}>
              <Button
                type="button"
                variant="brand"
                size="large"
                className="rounded-lg bg-indigo-600 text-white hover:bg-indigo-500"
                onClick={handleSave}
                disabled={saving}
                style={{ width: '100%' }}
              >
                {saving ? '保存中...' : '保存'}
              </Button>
            </Form.Item>
          </div>
        </Form>
      </Card>

      <Card
        className={`${styles.card} ${styles.researchProfileCard}`}
        title={<span className={styles.cardTitle}><Sparkles size={15} /> 科研画像</span>}
        extra={(
          <Button
            type="button"
            variant="ghost"
            size="small"
            onClick={handleGenerateProfile}
            disabled={profileGenerating}
          >
            {profileGenerating ? '模型分析中…' : researchProfile ? '重新生成' : '生成画像'}
          </Button>
        )}
      >
        {profileLoading ? (
          <div className={styles.profileLoading}><Spin size="small" /> 正在读取最近画像…</div>
        ) : !researchProfile ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="先完善上方资料，再由模型把兴趣、自述技能与已审核记录整理成科研画像"
          />
        ) : (
          <div className={styles.profileBody}>
            {profileStale && (
              <div className={styles.staleNotice}>
                <AlertTriangle size={15} /> 个人信息或成长记录已变化，请重新生成后再使用这份画像。
              </div>
            )}
            <div className={styles.profileMeta}>
              <span><ShieldCheck size={14} /> Review {researchProfile.review_status}</span>
              <span>{new Date(researchProfile.generated_at).toLocaleString('zh-CN')}</span>
            </div>
            <p className={styles.profileSummary}>{researchProfile.summary}</p>

            <section className={styles.profileSection}>
              <h3>能力证据阶梯</h3>
              {researchProfile.capabilities.length === 0 ? (
                <span className={styles.growthEmpty}>尚无足够信息形成能力判断</span>
              ) : (
                <div className={styles.capabilityGrid}>
                  {researchProfile.capabilities.map((item) => (
                    <article key={`${item.name}-${item.level}`} className={styles.capabilityItem}>
                      <div className={styles.capabilityHeading}>
                        <strong>{item.name}</strong>
                        <Tag color={item.level === 'unknown' ? 'default' : 'blue'}>{LEVEL_LABELS[item.level]}</Tag>
                        <Tag color={item.evidence_status === 'reviewed' ? 'green' : item.evidence_status === 'self_reported' ? 'gold' : 'default'}>
                          {item.evidence_status === 'reviewed' ? '已审核证据' : item.evidence_status === 'self_reported' ? '用户自述' : '未知'}
                        </Tag>
                      </div>
                      <p>{item.assessment}</p>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <div className={styles.profileColumns}>
              <section className={styles.profileSection}>
                <h3>研究方向</h3>
                {researchProfile.directions.map((item) => (
                  <div key={item.name} className={styles.profileListItem}>
                    <strong>{item.name}</strong><Tag>{item.status}</Tag>
                    <p>{item.rationale}</p>
                  </div>
                ))}
              </section>
              <section className={styles.profileSection}>
                <h3>当前缺口</h3>
                {researchProfile.gaps.map((item) => (
                  <div key={item.gap} className={styles.profileListItem}>
                    <strong>{item.gap}</strong>
                    <p>{item.why_it_matters}</p>
                  </div>
                ))}
              </section>
            </div>

            <section className={styles.profileSection}>
              <h3><Target size={14} /> 下一步可验证行动</h3>
              <ol className={styles.actionList}>
                {researchProfile.next_actions.map((item) => (
                  <li key={item.action}>
                    <strong>{item.action}</strong>
                    <span>交付物：{item.deliverable}</span>
                    <span>验收：{item.acceptance_criteria.join('；')}</span>
                  </li>
                ))}
              </ol>
            </section>

            {researchProfile.missing_information.length > 0 && (
              <div className={styles.missingInfo}>
                <strong>仍缺少的信息</strong>
                <span>{researchProfile.missing_information.join('；')}</span>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card className={`${styles.card} ${styles.growthCard}`} style={{ marginTop: 20 }} title={<span className="inline-flex items-center gap-2 text-slate-600"><BookOpen size={14} strokeWidth={1.5} className="text-slate-600" /> 科研成长状态</span>}>
        <p className={styles.growthHint}>只读记录：匹配成功与论文阅读会自动写回，不在此表单编辑。</p>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>已匹配导师</div>
          {growth.matched_mentors.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无匹配记录" />
          ) : (
            <div className={styles.growthTags}>
              {growth.matched_mentors.map((m) => (
                <Tag key={m.id}>{m.name}</Tag>
              ))}
            </div>
          )}
        </div>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>关注方向</div>
          {growth.directions.length === 0 ? (
            <span className={styles.growthEmpty}>尚无方向</span>
          ) : (
            <div className={styles.growthTags}>
              {growth.directions.map((d) => (
                <Tag key={d}>{d}</Tag>
              ))}
            </div>
          )}
        </div>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>有证据的方向假设</div>
          {growth.direction_hypotheses.length === 0 ? (
            <span className={styles.growthEmpty}>尚无通过审核的方向假设</span>
          ) : (
            growth.direction_hypotheses.map((item) => (
              <div key={item.id} className={styles.readItem}>
                <div className={styles.readMentor}>
                  {item.direction} <Tag>{item.status}</Tag>
                </div>
                <div className={styles.readTitle}>Evidence：{item.evidence_refs?.length ?? 0}</div>
              </div>
            ))
          )}
        </div>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>已读论文</div>
          {growth.read_papers.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未阅读导师论文" />
          ) : (
            growth.read_papers.map((item) => (
              <div key={item.candidate_id} className={styles.readItem}>
                <div className={styles.readMentor}>{item.mentor_name || item.candidate_id}</div>
                {(item.titles ?? []).slice(0, 8).map((title) => (
                  <div key={title} className={styles.readTitle}>{title}</div>
                ))}
              </div>
            ))
          )}
        </div>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>已验证科研经历</div>
          {growth.verified_experiences.length === 0 ? (
            <span className={styles.growthEmpty}>尚无通过 Review 的经历</span>
          ) : (
            growth.verified_experiences.map((item) => (
              <div key={item.id} className={styles.readItem}>
                <div className={styles.readMentor}>{item.summary}</div>
                <div className={styles.readTitle}>
                  Evidence：{item.evidence_refs?.length ?? 0} · Run：{item.source_run_id || '—'}
                </div>
              </div>
            ))
          )}
        </div>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>研究任务</div>
          {growth.research_tasks.length === 0 ? (
            <span className={styles.growthEmpty}>尚无研究任务</span>
          ) : (
            growth.research_tasks.map((task) => (
              <div key={task.id} className={styles.readItem}>
                <div className={styles.readMentor}>
                  {task.title} <Tag>{task.status}</Tag>
                </div>
                {task.acceptance_criteria.map((criterion) => (
                  <div key={criterion} className={styles.readTitle}>· {criterion}</div>
                ))}
              </div>
            ))
          )}
        </div>
        <div className={styles.growthBlock}>
          <div className={styles.growthLabel}>审核产物</div>
          {growth.artifacts.length === 0 ? (
            <span className={styles.growthEmpty}>尚无审核产物</span>
          ) : (
            <div className={styles.growthTags}>
              {growth.artifacts.map((artifact) => (
                <Tag key={artifact.id}>{artifact.title}</Tag>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

export default ProfilePage;
