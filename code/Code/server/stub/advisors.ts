/**
 * 导师 stub 数据字典（单一数据源）。
 *
 * routes/advisors.ts、routes/agent.ts、routes/email.ts、routes/pdf.ts、
 * routes/recommend.ts 共用本字典，避免多份重复定义出现字段不一致。
 *
 * 队友 C（爬虫/知识库）交付后，把本文件改为从真实 DB 查询并导出同形态
 * 数组/字典即可，调用方零改动；或保留本文件作开发兜底，由各路由切换
 * 到真实查询。响应契约（AdvisorDetail / Advisor / {explanation}）不变。
 *
 * id '1'~'8' 与 routes/agent.ts 的 mock 检索结果对齐，便于从检索结果
 * 点进详情、邮件、推荐都命中同一批导师。
 */

export interface StubAdvisorDetail {
  id: string;
  name: string;
  title: string;
  department: string;
  tags: string[];
  hIndex: number;
  papers: number;
  matchScore: number;
  explanation: string;
  bio: string;
  contact: string;
  recruiting: string;
  recentPapers: { title: string; year: number; venue: string }[];
}

export const ADVISORS: Record<string, StubAdvisorDetail> = {
  '1': {
    id: '1', name: '王某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['计算机视觉', '深度学习', '图像处理'],
    hIndex: 28, papers: 152, matchScore: 92,
    explanation: '查询"计算机视觉"→扩展为CV、图像处理、深度学习、目标检测\n王老师"计算机视觉"与"深度学习"语义相似度 92%\n近5年论文15篇，H指数28 (OpenAlex)\n院系与你专业匹配 ✅',
    bio: '主要从事计算机视觉与深度学习研究，聚焦目标检测、图像分割等方向，长期承担本科生科研训练指导。',
    contact: 'wangmo@ustc.edu.cn · 计算机楼 503',
    recruiting: '招收硕士/博士，欢迎对计算机视觉有热情的本科生进组',
    recentPapers: [
      { title: '基于 Transformer 的实时目标检测', year: 2024, venue: 'CVPR' },
      { title: '小样本图像分割的对比学习方法', year: 2023, venue: 'ICCV' },
      { title: '面向自动驾驶的场景理解综述', year: 2022, venue: 'TPAMI' },
    ],
  },
  '2': {
    id: '2', name: '李某某', title: '副教授', department: '信息科学技术学院',
    tags: ['计算机视觉', '模式识别', '医学图像'],
    hIndex: 19, papers: 87, matchScore: 85,
    explanation: '查询"计算机视觉"→扩展为CV、图像处理、深度学习\n李老师"模式识别"与"计算机视觉"语义相关度 85%\nH指数19，近年论文12篇',
    bio: '研究方向为医学图像分析与模式识别，与附属第一医院有长期合作。',
    contact: 'limo@ustc.edu.cn',
    recruiting: '招收硕士，偏好有 Python/PyTorch 基础的同学',
    recentPapers: [
      { title: '肺结节 CT 影像的弱监督检测', year: 2023, venue: 'MICCAI' },
      { title: '医学图像配准的深度学习方法', year: 2022, venue: 'TMI' },
    ],
  },
  '3': {
    id: '3', name: '张某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['计算机视觉', '三维重建', 'SLAM'],
    hIndex: 35, papers: 203, matchScore: 78,
    explanation: '查询"计算机视觉"→扩展为CV\n张老师"三维重建"属CV子方向，语义相似度 78%\nH指数35，论文203篇',
    bio: '长期从事 SLAM、三维重建与机器人视觉研究，主持多项国家自然科学基金。',
    contact: 'zhangmo@ustc.edu.cn',
    recruiting: '招收博士，需扎实的数学与编程基础',
    recentPapers: [
      { title: '动态环境下的语义 SLAM', year: 2024, venue: 'ICRA' },
      { title: '基于神经辐射场的三维重建', year: 2023, venue: 'CVPR' },
    ],
  },
  '4': {
    id: '4', name: '赵某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['人工智能', '机器学习', '强化学习'],
    hIndex: 42, papers: 280, matchScore: 95,
    explanation: '查询"人工智能"→扩展为AI、机器学习、深度学习、强化学习、NLP\n赵老师"机器学习"与"强化学习"语义相似度 95%\nH指数42，近5年论文25篇',
    bio: '从事机器学习与强化学习理论与应用研究，关注决策智能体与元学习。',
    contact: 'zhaomo@ustc.edu.cn',
    recruiting: '常年招收硕博，欢迎数学好的本科生',
    recentPapers: [
      { title: '离线强化学习的保守值估计', year: 2024, venue: 'NeurIPS' },
      { title: '元学习在少样本任务中的应用', year: 2023, venue: 'ICML' },
    ],
  },
  '5': {
    id: '5', name: '孙某某', title: '教授', department: '大数据学院',
    tags: ['人工智能', '数据挖掘', '知识图谱'],
    hIndex: 31, papers: 165, matchScore: 88,
    explanation: '查询"人工智能"→扩展为AI、机器学习\n孙老师"数据挖掘"与"人工智能"语义相关度 88%\nH指数31',
    bio: '研究方向为数据挖掘与知识图谱，应用于医疗与金融领域。',
    contact: 'sunmo@ustc.edu.cn',
    recruiting: '招收硕士',
    recentPapers: [
      { title: '知识图谱补足的图神经网络', year: 2023, venue: 'WWW' },
      { title: '时序数据的异常检测', year: 2022, venue: 'KDD' },
    ],
  },
  '6': {
    id: '6', name: '周某某', title: '副教授', department: '信息科学技术学院',
    tags: ['人工智能', '自然语言处理', '大语言模型'],
    hIndex: 24, papers: 98, matchScore: 82,
    explanation: '查询"人工智能"→扩展为AI、NLP\n周老师"NLP"属AI子方向，语义相似度 82%',
    bio: '研究自然语言处理与大语言模型，关注低资源学习与可解释性。',
    contact: 'zhoumo@ustc.edu.cn',
    recruiting: '招收硕士/博士，熟悉 PyTorch 与 Transformer 者优先',
    recentPapers: [
      { title: '低资源场景下的预训练适配', year: 2024, venue: 'ACL' },
      { title: '大模型推理链的可解释分析', year: 2023, venue: 'EMNLP' },
    ],
  },
  '7': {
    id: '7', name: '吴某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['数据库', '大数据', '分布式系统'],
    hIndex: 36, papers: 210, matchScore: 70,
    explanation: '根据关键词综合匹配\n吴老师研究方向与查询部分相关',
    bio: '从事数据库与分布式系统研究，关注云原生数据管理。',
    contact: 'wumo@ustc.edu.cn',
    recruiting: '招收硕士',
    recentPapers: [
      { title: '云原生数据库的弹性伸缩', year: 2023, venue: 'SIGMOD' },
      { title: '分布式事务的乐观并发控制', year: 2022, venue: 'VLDB' },
    ],
  },
  '8': {
    id: '8', name: '郑某某', title: '教授', department: '数学科学学院',
    tags: ['优化理论', '机器学习', '统计学习'],
    hIndex: 29, papers: 140, matchScore: 65,
    explanation: '根据关键词综合匹配\n郑老师研究方向与查询存在交叉',
    bio: '研究优化理论与统计学习，为机器学习提供数学基础。',
    contact: 'zhengmo@ustc.edu.cn',
    recruiting: '招收对数学有兴趣的硕博生',
    recentPapers: [
      { title: '非凸优化的逃离鞍点分析', year: 2023, venue: 'JMLR' },
      { title: '高维统计的稀疏恢复', year: 2022, venue: 'Annals of Statistics' },
    ],
  },
};

/** 全部导师列表（顺序稳定） */
export const ADVISOR_LIST: StubAdvisorDetail[] = Object.values(ADVISORS).sort((a, b) =>
  Number(a.id) - Number(b.id),
);

/** 安全解析 SQLite 中的 JSON 字符串数组字段 */
export function safeParseArray(val: string | undefined | null): string[] {
  if (!val) return [];
  try {
    const parsed = JSON.parse(val);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
