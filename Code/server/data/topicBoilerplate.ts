/** USTC homepage template residue and scraped nav/recruit noise. */

const BOILERPLATE_MARKERS = [
  '版权所有',
  '地址：',
  '联系地址',
  '邮编',
  '邮政编码',
  '手机版',
  'Copyright',
  'Contact information',
];

const POSTAL_CODE = /(?:邮\s*编|邮政编码).{0,12}\d{5,6}|^\d{6}$/;

const WEB_NAV_TOKENS = new Set([
  '登录', '注册', '首页', '新闻', '通知', '公告', '下载', '链接', '更多', '相册',
  '概况', '简介', '导航', '栏目', '搜索', '主页', '网站', '版权', '备案', '友情',
  '站点', '登出', '注销', '收藏', '设置', '帮助', '关于', '联系', '新闻动态',
  '科研进展', '科研概况', '教学资源', '组内相册', '团队风采', '团队介绍', '招生招聘',
  '招生须知', '其他栏目', '实验室概况', '研究兴趣', '主要研究方向但不局限于以下',
  '团队名称', '指导研究生及博士后', '已毕业研究生/已出站博士后', '招生要求（满足其一',
  '本科生｜硕士生｜博士生｜博士后｜特任副研究员',
]);

const RECRUIT_HINT = /招生|招聘|招收|欢迎[\s\S]{0,6}加入|个人陈述|简历|题目注明|发送至|满足其一|联合培养|博士后申请|青年才俊|团队协作精神|有意者请|成绩单发至/;
const PAPER_LINE_HINT = /DOI:|Distinguished Paper|Wiley|IEEE Transactions|JSSC|Nature Physics|Nature Nanotechnol|Adv\. Mater|J Am Chem Soc|Journal of the American Chemical Society|Light: Science|Geophysical Research Letters|Geochimica et Cosmochimica Acta|Applied Catalysis B/;
const BIOGRAPHY_HINT = /^(?:截至目前|近些年|近年来|迄今|以第一|通讯作者|作者身份|an? adjunct|University of|a brief introduction)/i;
const TITLE_LABEL = /^(博士生导师|硕士生导师|特任副研究员|博士后 \/ 副研究员|🧑‍🔬 博士后 \/ 副研究员|Special Associate Researcher)$/;

export function isBoilerplateTopic(topic: string): boolean {
  const text = String(topic || '').replace(/\s+/g, ' ').trim();
  if (!text) return true;
  if (POSTAL_CODE.test(text)) return true;
  return BOILERPLATE_MARKERS.some((marker) => text.includes(marker));
}

/** 网页导航 / 招生话术 / 计数器 / 人名噪声（来自 feature 脏词规则，保守过滤）。 */
export function isDirtyTopic(topic: string, mentorName?: string): boolean {
  const s = String(topic || '').trim();
  if (!s) return true;
  if (/访问量|点击量|点击数|访问统计/.test(s)) return true;
  if (WEB_NAV_TOKENS.has(s)) return true;
  if (RECRUIT_HINT.test(s)) return true;
  if (BIOGRAPHY_HINT.test(s)) return true;
  if (/^[“"].+[”"]$/.test(s)) return true;
  if (/@[a-zA-Z0-9._-]+\.(edu|com|org|cn)/.test(s)) return true;
  if (/https?:\/\//.test(s)) return true;
  if (/电子邮箱：|邮箱：/.test(s)) return true;
  if (TITLE_LABEL.test(s)) return true;
  if (/^指导研究生/.test(s)) return true;
  if (PAPER_LINE_HINT.test(s)) return true;
  if (mentorName && s === mentorName) return true;
  if (/欢迎|点赞|转发|下载|收藏|订阅|关注|扫码|点赞关注/.test(s) && s.length <= 12) return true;
  if (/^[\d\-\/\.\s:：、]+$/.test(s)) return true;
  if (/^第[一二三四五六七八九十\d]+季度/.test(s)) return true;
  if (/Distinguished Paper|实习|奖学金|Best Paper|优秀青年|杰出青年|人才计划/.test(s)) return true;
  return false;
}

/**
 * 官网有时把多个研究方向抓成一整句。先按明确的句/分号边界拆开，再逐段判噪声，
 * 避免“凝聚态物理。专注于……”或较长英文方向被整条丢弃。
 */
function topicFragments(value: string): string[] {
  const pieces = value
    .split(/[。；;]+/)
    .map((item) => item
      .replace(/^[，,、\s]+|[，,、\s]+$/g, '')
      .replace(/^(?:主要)?研究方向包括\s*/i, '')
      .replace(/^(?:专注于|致力于)\s*/i, '')
      .replace(/^My current research interests? (?:mainly )?focus(?:es)? on\s*/i, '')
      .trim())
    .filter(Boolean);
  return pieces.length ? pieces : [value];
}

export function cleanTopics(values: unknown, mentorName?: string): string[] {
  if (!Array.isArray(values)) return [];
  const seen = new Set<string>();
  const cleaned: string[] = [];
  for (const raw of values) {
    const text = String(raw || '').replace(/\s+/g, ' ').trim();
    if (!text) continue;
    for (const fragment of topicFragments(text)) {
      if (isBoilerplateTopic(fragment) || isDirtyTopic(fragment, mentorName)) continue;
      const key = fragment.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      cleaned.push(fragment);
    }
  }
  return cleaned;
}
