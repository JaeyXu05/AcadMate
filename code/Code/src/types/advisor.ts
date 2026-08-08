import type { Advisor } from './search';

/**
 * 导师详情（扩展检索用的 Advisor）。
 *
 * 字段对齐说明：当前为 D（网站搭建）侧的临时定义。
 * C（爬虫/知识库）交付后若字段名/结构有差异，在 services/advisor.ts 的
 * service 层做映射，保持本类型不变，组件零改动。
 */
export interface AdvisorPaper {
  title: string;
  year?: number;
  venue?: string;
}

export interface AdvisorDetail extends Advisor {
  /** 个人简介 */
  bio?: string;
  /** 邮箱/办公室等联系方式 */
  contact?: string;
  /** 代表论文 */
  recentPapers?: AdvisorPaper[];
  /** 招生意向（如：招收硕士/博士、对本科生友好） */
  recruiting?: string;
}

/** GET /advisors/:id/explanation 响应 */
export interface AdvisorExplanation {
  explanation: string;
}
