import { useState } from 'react';
import { Modal, Form, Input, Checkbox, App } from 'antd';
import { Mail, Lock } from 'lucide-react';
import { useAuthStore } from '../stores/authStore';
import Button from './Button';

interface LoginModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function LoginModal({ open, onClose, onSuccess }: LoginModalProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const { message } = App.useApp();

  const handleSubmit = async (values: { email: string; password: string; rememberMe: boolean }) => {
    setLoading(true);
    try {
      await login(values.email, values.password, values.rememberMe ?? false);
      message.success('登录成功');
      onClose();
      onSuccess();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '登录失败，请重试';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="登录"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
      centered
      width={400}
    >
      <p style={{ color: '#78716c', fontSize: 13, marginBottom: 16, textAlign: 'center' }}>
        首次登录将自动创建账号
      </p>

      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{ rememberMe: false }}
        requiredMark={false}
      >
        <Form.Item
          name="email"
          label="邮箱"
          rules={[
            { required: true, message: '请输入邮箱' },
            { type: 'email', message: '邮箱格式不正确' },
          ]}
        >
          <Input
            className="input-quiet"
            prefix={<Mail size={14} strokeWidth={1.5} className="text-slate-600" />}
            placeholder="请输入邮箱"
            size="large"
            autoComplete="email"
          />
        </Form.Item>

        <Form.Item
          name="password"
          label="密码"
          rules={[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少 6 位' },
          ]}
        >
          <Input.Password
            className="input-quiet"
            prefix={<Lock size={14} strokeWidth={1.5} className="text-slate-600" />}
            placeholder="请输入密码（至少 6 位）"
            size="large"
            autoComplete="current-password"
          />
        </Form.Item>

        <Form.Item name="rememberMe" valuePropName="checked">
          <Checkbox>记住我</Checkbox>
        </Form.Item>

        <Form.Item style={{ marginBottom: 0 }}>
          <Button
            type="submit"
            variant="brand"
            size="large"
            style={{ width: '100%' }}
            disabled={loading}
          >
            {loading ? '登录中...' : '登 录'}
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default LoginModal;