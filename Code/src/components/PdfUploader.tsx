import { useState } from 'react';
import { Upload, Button, App } from 'antd';
import { Upload as UploadIcon, File } from 'lucide-react';
import type { UploadProps } from 'antd';
import { uploadPdf } from '../services/pdf';

interface PdfUploaderProps {
  /** 上传成功后回传 upload_id 与文件名 */
  onUploaded?: (upload_id: string, filename: string) => void;
  /** 上传中状态切换（可选） */
  onUploadingChange?: (uploading: boolean) => void;
  uploadFn?: (file: File) => Promise<{ upload_id: string; filename: string }>;
}

/**
 * PDF 上传组件：用普通 AntD Upload + 紧凑按钮，自行调后端 /upload/pdf，
 * 阻止 AntD 默认的内部上传行为。上传成功后通过 onUploaded 回传 upload_id。
 * 不使用拖拽区，保持上传入口轻量。
 */
function PdfUploader({ onUploaded, onUploadingChange, uploadFn }: PdfUploaderProps) {
  const { message } = App.useApp();
  const [uploadingCount, setUploadingCount] = useState(0);
  const uploading = uploadingCount > 0;

  const uploadProps: UploadProps = {
    name: 'file',
    multiple: true,
    maxCount: 20,
    accept: 'application/pdf,.pdf',
    // 文件统一显示在 PdfPage 的“PDF 历史记录”里，避免 Upload 内部列表只保留当前一次选择。
    showUploadList: false,
    beforeUpload: (file) => {
      // 校验类型
      const isPdf =
        file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      if (!isPdf) {
        message.error('仅支持 PDF 文件');
        return Upload.LIST_IGNORE;
      }
      // 校验大小（≤20MB，与后端 multer 限制一致）
      if (file.size > 20 * 1024 * 1024) {
        message.error('文件不能超过 20MB');
        return Upload.LIST_IGNORE;
      }
      return true; // 放行到 customRequest
    },
    customRequest: async (options) => {
      const { file, onSuccess, onError } = options;
      setUploadingCount((count) => count + 1);
      onUploadingChange?.(true);
      try {
        const res = uploadFn
          ? await uploadFn(file as File)
          : await uploadPdf(file as File);
        const localName = typeof file === 'object' && file && 'name' in file
          ? String((file as File).name || '')
          : '';
        onSuccess?.(res);
        onUploaded?.(res.upload_id, localName || res.filename);
        message.success(`已上传：${res.filename}`);
      } catch (err) {
        onError?.(err as Error);
        const msg =
          err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { message?: string } } }).response?.data?.message
            : undefined;
        message.error(msg ?? '上传失败，请重试');
      } finally {
        setUploadingCount((count) => Math.max(0, count - 1));
        onUploadingChange?.(false);
      }
    },
  };

  return (
    <div>
      <Upload {...uploadProps} disabled={uploading}>
        <Button icon={<UploadIcon size={14} strokeWidth={1.5} className="text-slate-600" />} loading={uploading}>
          选择 PDF 文件
        </Button>
      </Upload>
      <div className="mt-2 text-[13px] text-slate-500">
        <File size={14} strokeWidth={1.5} className="mr-1.5 inline text-slate-600" />
        支持同时选择多个 PDF，单文件不超过 20MB
      </div>
    </div>
  );
}

export default PdfUploader;
