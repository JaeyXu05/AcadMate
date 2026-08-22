import { useState } from 'react';
import { Upload, Button, App } from 'antd';
import { UploadOutlined, FilePdfOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { uploadPdf } from '../services/pdf';

interface PdfUploaderProps {
  /** 上传成功后回传 upload_id 与文件名 */
  onUploaded: (upload_id: string, filename: string) => void;
  /** 上传中状态切换（可选） */
  onUploadingChange?: (uploading: boolean) => void;
}

/**
 * PDF 上传组件：用普通 AntD Upload + 紧凑按钮，自行调后端 /upload/pdf，
 * 阻止 AntD 默认的内部上传行为。上传成功后通过 onUploaded 回传 upload_id。
 * 不使用拖拽区，保持上传入口轻量。
 */
function PdfUploader({ onUploaded, onUploadingChange }: PdfUploaderProps) {
  const { message } = App.useApp();
  const [uploading, setUploading] = useState(false);

  const uploadProps: UploadProps = {
    name: 'file',
    multiple: false,
    maxCount: 1,
    accept: 'application/pdf,.pdf',
    showUploadList: true,
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
      setUploading(true);
      onUploadingChange?.(true);
      try {
        const res = await uploadPdf(file as File);
        onSuccess?.(res);
        onUploaded(res.upload_id, res.filename);
        message.success(`已上传：${res.filename}`);
      } catch (err) {
        onError?.(err as Error);
        const msg =
          err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { message?: string } } }).response?.data?.message
            : undefined;
        message.error(msg ?? '上传失败，请重试');
      } finally {
        setUploading(false);
        onUploadingChange?.(false);
      }
    },
  };

  return (
    <div>
      <Upload {...uploadProps} disabled={uploading}>
        <Button icon={<UploadOutlined />} loading={uploading}>
          选择 PDF 文件
        </Button>
      </Upload>
      <div style={{ marginTop: 8, color: 'rgba(255,255,255,0.4)', fontSize: 13 }}>
        <FilePdfOutlined style={{ marginRight: 6 }} />
        支持 PDF 格式，单文件不超过 20MB
      </div>
    </div>
  );
}

export default PdfUploader;
