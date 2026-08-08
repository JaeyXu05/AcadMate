import type { Advisor } from './search';

/**
 * 猜你喜欢响应契约。
 *
 * 字段对齐说明：当前为 D（网站搭建）侧临时定义。
 * 队友 A/C 交付真实推荐后若结构有差异，在 services/recommend.ts 的
 * service 层做映射，保持本类型不变，组件零改动。
 */

/** GET /recommend 响应 */
export interface RecommendResponse {
  /** 推荐导师列表（已按推荐度排序） */
  recommendations: Advisor[];
  /** 推荐依据（命中的兴趣/技能关键词，用于页面说明） */
  basedOn: string[];
}
