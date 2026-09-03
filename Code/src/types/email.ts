/** 邮件生成请求 */
export interface EmailGenerateRequest {
  advisor_id: string;
}

/** 邮件生成响应 / 草稿 */
export interface EmailDraft {
  subject: string;
  body: string;
  default_recipients?: string[];
}
