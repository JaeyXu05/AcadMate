/**
 * 云图相关类型契约。
 *
 * 这份类型已与 3D 云图数据 `paper-claw-master/data` 生成的 `cloud_data.json`
 * 对齐：节点承载银河盘坐标(x/y/z)、领域、亮度、大小等可视化字段，
 * 前端 `CloudGraph` 组件用 Three.js 渲染真实导师网络。
 *
 * 云图数据由后端 `GET /api/cloud/graph` 提供（见 server/routes/cloud.ts），
 * 前端 service (`services/cloud.ts`) 直接消费，无需在组件内做布局计算。
 */

/** 云图节点：一个导师 */
export interface CloudNode {
  /** 唯一 id，对应 Advisor.id / RAG candidate_id */
  id: string;
  /** 导师姓名 */
  name: string;
  /** 院系 / 单位 */
  department?: string;
  /** 研究方向标签（用于聚类/着色） */
  tags?: string[];
  /** H 指数（可影响节点大小） */
  hIndex?: number;
  /** 论文数（可影响节点大小） */
  papers?: number;
  /** 匹配度 0-100（可选，来自当前检索结果） */
  matchScore?: number;

  // ===== 3D 可视化字段（与 cloud_data.json 对齐，由后端生成）=====
  /** 研究领域 id（用于聚类/图例/聚焦） */
  domain?: string;
  /** 领域名 */
  domain_name?: string;
  /** 领域主色（十六进制字符串） */
  color?: string;
  /** 相对亮度 0.55~1.0（研究方向/论文多的更亮） */
  lum?: number;
  /** 径向亮度因子 0~1（越靠中心越亮） */
  core_lum?: number;
  /** 星体大小（研究/论文丰富度） */
  size?: number;
  /** 3D 坐标（后端已按银河盘布局预计算，非归一化，单位同云图场景） */
  x?: number;
  y?: number;
  z?: number;
  /** 研究方向明细（详情面板展示） */
  topics?: string[];
  /** 研究方法（详情面板展示） */
  methods?: string[];
  /** 代表论文标题列表 */
  pubs?: string[];
  /** 论文总数 */
  pub_count?: number;
  /** 个人主页 */
  homepage?: string;
  /** 招生意向文本 */
  recruitment?: string;
}

/** 云图边：两个导师之间的关系 */
export interface CloudEdge {
  /** 起点 id */
  source: string;
  /** 终点 id */
  target: string;
  /** 关系强度 0-1，可影响连线粗细/透明度 */
  weight?: number;
  /** 关系类型，如 'coauthor'（合作发文）/ 'same-field'（同方向），用于着色 */
  relation?: 'coauthor' | 'same-field' | 'citation' | string;
}

/** 云图组件必须实现的 props 契约（CloudGraph.tsx） */
export interface CloudGraphProps {
  /** 全部节点 */
  nodes: CloudNode[];
  /** 全部边 */
  edges: CloudEdge[];
  /** 当前选中节点 id（用于高亮） */
  selectedId?: string;
  /** 点击/选中某个节点时回调 */
  onSelectNode?: (id: string | null) => void;
  /** 悬停某个节点时回调（id 或 null），渲染层节流触发，供外层做悬浮卡 */
  onHoverNode?: (id: string | null) => void;
  /** 数据是否加载中（组件可自行展示 loading 态，也可交给外层） */
  loading?: boolean;
  /** 自定义 className / style 透传 */
  className?: string;
  style?: React.CSSProperties;
}

/** 云图数据加载结果 */
export interface CloudData {
  nodes: CloudNode[];
  edges: CloudEdge[];
  /** 顶层元信息（图例、相机参数、统计等），供 CloudGraph/CloudPage 可选使用 */
  meta?: {
    title?: string;
    mentor_count?: number;
    domain_count?: number;
    legend?: { id: string; name: string; color: string; count: number }[];
    camera?: { target?: [number, number, number]; radius?: number; r_out?: number; r_in?: number; arms?: number };
  };
}