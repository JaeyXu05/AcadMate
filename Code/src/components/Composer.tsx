import { useState, useRef, useEffect } from 'react';
import { Input, Button, Upload, App } from 'antd';
import type { UploadProps } from 'antd';
import { Send, Paperclip, X } from 'lucide-react';
import { useSearchStore } from '../stores/searchStore';
import { uploadPdf } from '../services/pdf';
import styles from './ChatWindow.module.css';

const { TextArea } = Input;

interface ComposerProps {
  /** 占位提示文案 */
  placeholder?: string;
}

/**
 * 底部输入区（Composer）—— 嵌在中间 Workspace 列底部，宽度随中间列拖拽变化。
 * §7.1 统一输入：支持 PDF 与文字同入一次 Mission（PDF → upload_id 随检索发出）。
 * 发送逻辑不变：写入 user 消息 + pendingUploadId，由 SearchPage 的 useEffect 监听触发 SSE。
 * 「新对话」按钮已上移到中间列顶部标题栏（由 SearchPage 渲染），本组件不再包含。
 */
function Composer({ placeholder = '描述你想找的导师方向，可附 PDF 论文…' }: ComposerProps) {
  const { message } = App.useApp();
  const [inputValue, setInputValue] = useState('');
  const [uploading, setUploading] = useState(false);
  const [attachedName, setAttachedName] = useState<string | null>(null);
  const isStreaming = useSearchStore((s) => s.isStreaming);
  const pendingUploadId = useSearchStore((s) => s.pendingUploadId);
  const setPendingUploadId = useSearchStore((s) => s.setPendingUploadId);

  const uploadProps: UploadProps = {
    name: 'file',
    multiple: false,
    maxCount: 1,
    accept: 'application/pdf,.pdf',
    showUploadList: false,
    beforeUpload: (file) => {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      if (!isPdf) {
        message.error('仅支持 PDF 文件');
        return Upload.LIST_IGNORE;
      }
      if (file.size > 20 * 1024 * 1024) {
        message.error('文件不能超过 20MB');
        return Upload.LIST_IGNORE;
      }
      return true;
    },
    customRequest: async (options) => {
      const { file, onSuccess, onError } = options;
      setUploading(true);
      try {
        const res = await uploadPdf(file as File);
        onSuccess?.(res);
        setPendingUploadId(res.upload_id);
        setAttachedName(res.filename);
        message.success(`已附上：${res.filename}`);
      } catch (err) {
        onError?.(err as Error);
        const msg =
          err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { message?: string } } }).response?.data?.message
            : undefined;
        message.error(msg ?? '上传失败，请重试');
      } finally {
        setUploading(false);
      }
    },
  };

  const handleRemoveAttach = () => {
    setPendingUploadId(null);
    setAttachedName(null);
  };

  const handleSend = () => {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming) return;
    setInputValue('');
    // 触发 SSE 由 SearchPage 的 useEffect 监听新 user 消息来调用
    useSearchStore.getState().addUserMessage(trimmed);
    // pendingUploadId 由 SearchPage 发送后清空，这里仅清本地展示名（发送瞬间保留 id 供消费）
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 自动聚焦
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <div className={styles.composerWrap}>
      {attachedName && (
        <div className={styles.attachChip}>
          <span className={styles.attachName}>{attachedName}</span>
          <button
            type="button"
            className={styles.attachRemove}
            onClick={handleRemoveAttach}
            disabled={isStreaming}
            title="移除附件"
          >
            <X size={14} strokeWidth={1.5} className="text-slate-600" />
          </button>
        </div>
      )}
      <div className={styles.chatFooter}>
        {/* 附件上传：单独一行，置于输入框上方 */}
        <div className={styles.attachRow}>
          <Upload {...uploadProps} disabled={uploading || isStreaming} showUploadList={false}>
            <Button
              icon={<Paperclip size={14} strokeWidth={1.5} className="text-slate-600" />}
              loading={uploading}
              disabled={isStreaming}
              title="附上 PDF 论文（统一输入）"
              size="small"
            >
              附上文件
            </Button>
          </Upload>
          <span className={styles.attachRowHint}>支持 PDF，可与文字一起检索</span>
        </div>
        <div className={styles.inputRow}>
          <TextArea
            ref={inputRef as any}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            autoSize={{ minRows: 4, maxRows: 10 }}
            disabled={isStreaming}
            className="input-quiet"
            style={{ resize: 'none', fontSize: 16, padding: '14px 16px', lineHeight: 1.6 }}
          />
          <Button
            type="primary"
            icon={<Send size={14} strokeWidth={1.5} className="text-slate-600" />}
            onClick={handleSend}
            loading={isStreaming}
            disabled={(!inputValue.trim() && !pendingUploadId) || isStreaming}
            style={{ height: 44, fontSize: 16, flexShrink: 0 }}
          >
            发送
          </Button>
        </div>
      </div>
    </div>
  );
}

export default Composer;
