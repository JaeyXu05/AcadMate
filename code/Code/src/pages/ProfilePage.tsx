import { useState } from 'react';
import { Form, Input, Select, Card, App } from 'antd';
import { UserOutlined, MailOutlined, BookOutlined, TeamOutlined } from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
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
  const { message } = App.useApp();

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
  const firstLetter = email ? email.charAt(0).toUpperCase() : 'U';
  const displayName = user?.nickname || email || '未命名用户';

  return (
    <div className={styles.container}>
      <PageCloseButton />
      {/* 头部标识区 */}
      <div className={styles.profileHeader}>
        <div className={styles.profileAvatar}>{firstLetter}</div>
        <div>
          <h2 className={styles.profileTitle}>个人信息</h2>
          <div className={styles.profileSubtitle}>{displayName}</div>
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
                prefix={<MailOutlined />}
                disabled
                size="large"
              />
            </Form.Item>

            <Form.Item name="nickname" label="昵称">
              <Input
                prefix={<UserOutlined />}
                placeholder="给自己取个昵称"
                size="large"
              />
            </Form.Item>

            <Form.Item name="grade" label="年级">
              <Select
                placeholder="选择年级"
                options={GRADE_OPTIONS.map((g) => ({ label: g, value: g }))}
                size="large"
              />
            </Form.Item>

            <Form.Item name="major" label="专业 / 院系">
              <Input
                prefix={<TeamOutlined />}
                placeholder="如：计算机科学与技术学院"
                size="large"
              />
            </Form.Item>

            <Form.Item name="interests" label="研究方向" className={styles.formFull}>
              <Select
                mode="tags"
                placeholder="输入后按回车添加，如：计算机视觉、深度学习"
                size="large"
              />
            </Form.Item>

            <Form.Item name="skills" label="已有技能" className={styles.formFull}>
              <Select
                mode="tags"
                placeholder="输入后按回车添加，如：Python、PyTorch"
                size="large"
              />
            </Form.Item>

            <Form.Item name="bio" label="个人简介" className={styles.formFull}>
              <TextArea
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
    </div>
  );
}

export default ProfilePage;