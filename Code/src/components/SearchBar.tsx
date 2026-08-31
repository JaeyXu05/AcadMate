import { useState, useRef, useEffect } from 'react';
import { Input, Upload, App } from 'antd';
import type { UploadProps } from 'antd';
import { Send, Paperclip, X } from 'lucide-react';
import { useSearchStore } from '../stores/searchStore';
import { uploadPdf } from '../services/pdf';

const { TextArea } = Input;

interface SearchBarProps {
  placeholder?: string;
}

function SearchBar({ placeholder = '描述你想找的导师方向，可附 PDF 论文…' }: SearchBarProps) {
  const { message } = App.useApp();
  const [inputValue, setInputValue] = useState('');
  const [uploading, setUploading] = useState(false);
  const [attachedName, setAttachedName] = useState<string | null>(null);
  const isStreaming = useSearchStore((s) => s.isStreaming);
  const pendingUploadId = useSearchStore((s) => s.pendingUploadId);
  const setPendingUploadId = useSearchStore((s) => s.setPendingUploadId);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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

  const handleSend = () => {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming) return;
    setInputValue('');
    useSearchStore.getState().addUserMessage(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <div className="shrink-0 rounded-lg border border-slate-200 bg-white px-4 py-3">
      {attachedName && (
        <div className="mb-2 flex items-center gap-2 text-[12px] text-slate-500">
          <span className="truncate">{attachedName}</span>
          <button
            type="button"
            className="rounded px-1 text-slate-400 hover:bg-slate-50 hover:text-slate-700"
            onClick={() => {
              setPendingUploadId(null);
              setAttachedName(null);
            }}
            disabled={isStreaming}
            aria-label="移除附件"
          >
            <X size={14} strokeWidth={1.5} className="text-slate-500" />
          </button>
        </div>
      )}
      <div className="mb-2 flex items-center gap-3 text-[12px] text-slate-500">
        <Upload {...uploadProps} disabled={uploading || isStreaming} showUploadList={false}>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-50"
            disabled={uploading || isStreaming}
          >
            <Paperclip size={14} strokeWidth={1.5} className="text-indigo-500" />
            {uploading ? '上传中…' : '附上 PDF'}
          </button>
        </Upload>
        <span>可与文字一起检索</span>
      </div>
      <div className="flex items-center gap-3">
        <TextArea
          ref={inputRef as never}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoSize={{ minRows: 1, maxRows: 6 }}
          disabled={isStreaming}
          variant="borderless"
          className="search-field"
          style={{ resize: 'none', fontSize: 15, lineHeight: 1.5, background: 'transparent' }}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={(!inputValue.trim() && !pendingUploadId) || isStreaming}
          className="inline-flex h-10 shrink-0 items-center gap-1.5 self-center rounded-lg bg-indigo-600 px-3 text-[13px] font-medium text-white hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400"
        >
          <Send size={14} strokeWidth={1.5} className="text-white" />
          {isStreaming ? '检索中' : '发送'}
        </button>
      </div>
    </div>
  );
}

export default SearchBar;
