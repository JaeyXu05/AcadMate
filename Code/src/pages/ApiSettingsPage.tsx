import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Input, Switch } from 'antd';
import { KeyRound, Save } from 'lucide-react';
import PageCloseButton from '../components/PageCloseButton';
import { getUserApiSettings, updateUserApiSettings, type UserApiSettings } from '../services/user';
import styles from './SettingsPage.module.css';

function ApiSettingsPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [apiKeySaved, setApiKeySaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getUserApiSettings()
      .then((settings: UserApiSettings) => {
        if (cancelled) return;
        setEnabled(Boolean(settings.enabled));
        setBaseUrl(settings.base_url || '');
        setModel(settings.model || '');
        setApiKeySaved(Boolean(settings.api_key_saved));
      })
      .catch((error: unknown) => {
        message.error((error as { response?: { data?: { message?: string } } })?.response?.data?.message || '读取 API 设置失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [message]);

  const handleSave = async () => {
    if (!baseUrl.trim() || !model.trim()) {
      message.warning('请填写 API 地址和模型名称');
      return;
    }
    if (enabled && !apiKey.trim() && !apiKeySaved) {
      message.warning('启用前请先填写 API Key');
      return;
    }
    setSaving(true);
    try {
      const saved = await updateUserApiSettings({
        enabled,
        base_url: baseUrl.trim(),
        model: model.trim(),
        api_key: apiKey.trim() || undefined,
      });
      setApiKeySaved(Boolean(saved.api_key_saved));
      setApiKey('');
      message.success('API 设置已保存，后续模型功能会使用你自己的配置');
    } catch (error: unknown) {
      message.error((error as { response?: { data?: { message?: string } } })?.response?.data?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveKey = async () => {
    setSaving(true);
    try {
      await updateUserApiSettings({ remove_key: true });
      setApiKeySaved(false);
      setApiKey('');
      message.success('已清除保存的 API Key');
    } catch {
      message.error('清除失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />
      <Card className={styles.card} title="API 设置" loading={loading}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="平台默认 API 由启动向导写入（BASE_URL / MODEL / API_KEY）。"
          description="你可以在本页为当前登录账号单独覆盖：开启后，科研对话、画像、PDF 合并分析、计划和报告会优先使用你自己的 API 地址与 Key，且不会影响其他账号。"
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div>启用我自己的模型 API</div>
              <div style={{ fontSize: 12, color: '#78716c' }}>
                关闭时使用平台默认配置（若已配置）
              </div>
            </div>
            <Switch checked={enabled} onChange={setEnabled} />
          </div>
          <label style={{ display: 'block' }}>
            <div style={{ marginBottom: 6 }}>API 地址（Base URL）</div>
            <Input
              name="llm_base_url"
              autoComplete="off"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="填写 API 地址"
            />
          </label>
          <label style={{ display: 'block' }}>
            <div style={{ marginBottom: 6 }}>模型名称</div>
            <Input
              name="llm_model"
              autoComplete="off"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="填写模型名称"
            />
          </label>
          <label style={{ display: 'block' }}>
            <div style={{ marginBottom: 6 }}>
              API Key {apiKeySaved && <span style={{ color: '#16a34a', fontSize: 12 }}>（已保存，留空表示不修改）</span>}
            </div>
            <Input.Password
              name="llm_api_key"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={apiKeySaved ? '输入新 Key 可替换已保存的 Key' : '粘贴你的 API Key'}
              prefix={<KeyRound size={14} />}
            />
          </label>
          <div className={styles.resetRow} style={{ gap: 8 }}>
            {apiKeySaved && (
              <button className={styles.resetBtn} type="button" onClick={() => void handleRemoveKey()}>
                清除已保存 Key
              </button>
            )}
            <Button
              type="primary"
              icon={<Save size={14} />}
              loading={saving}
              onClick={() => void handleSave()}
            >
              保存 API 设置
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

export default ApiSettingsPage;
