import { useEffect, useState } from 'react';
import { Form, Input, Select, Card, App, Empty, Tag } from 'antd';
import { User, Mail, BookOpen, Users } from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import { getGrowth, emptyGrowth } from '../services/user';
import type { GrowthState } from '../types/auth';
import PageCloseButton from '../components/PageCloseButton';
import Button from '../components/Button';
import styles from './ProfilePage.module.css';

const { TextArea } = Input;

/** 年级选项 */
const GRADE_OPTIONS = [
  '大一', '大二', '大三', '大四',
  '研一', '研二', '研三',
  '博一', '博二', '博三', '博四', '博五',
  '已毕业', '其他',
];

function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [growth, setGrowth] = useState<GrowthState>(emptyGrowth());
  const { message } = App.useApp();

  useEffect(() => {
    getGrowth()
      .then(setGrowth)
      .catch(() => setGrowth(emptyGrowth()));
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

      <Card className={styles.card}>
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

      <Card className={styles.card} style={{ marginTop: 20 }} title={<span className="inline-flex items-center gap-2 text-slate-600"><BookOpen size={14} strokeWidth={1.5} className="text-slate-600" /> 科研成长状态</span>}>
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
