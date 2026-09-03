import type { RagMentor } from './ragAdvisors';
import { cleanTopics, stripEnumeratedPrefix } from './topicBoilerplate';

export type EmailScenarioId =
  | 'strong_research'
  | 'strong_gpa'
  | 'paper_reader'
  | 'summer'
  | 'thesis'
  | 'postgraduate'
  | 'cross_major'
  | 'limited_info';

export const EMAIL_SCENARIOS: Array<{ value: EmailScenarioId; label: string }> = [
  { value: 'postgraduate', label: '保研/考研联系导师' },
  { value: 'strong_research', label: '有科研/竞赛经历' },
  { value: 'strong_gpa', label: '成绩好但无科研经历' },
  { value: 'paper_reader', label: '认真读过老师论文' },
  { value: 'summer', label: '暑期/短期进组' },
  { value: 'thesis', label: '本科毕业设计进组' },
  { value: 'cross_major', label: '跨专业/转方向' },
  { value: 'limited_info', label: '主页信息有限' },
];

export interface ContactEmailContext {
  candidate: RagMentor;
  profile: Record<string, unknown>;
  papers: string[];
  memoryCore: string[];
}

function phraseList(value: unknown, limit = 8): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    const text = String(item ?? '').replace(/\s+/g, ' ').trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    result.push(text);
    if (result.length >= limit) break;
  }
  return result;
}

function valueOr(context: ContactEmailContext, key: string): string {
  return String(context.profile[key] ?? '').trim();
}

function name(context: ContactEmailContext): string {
  return valueOr(context, 'nickname') || valueOr(context, 'name') || '【姓名】';
}

function topics(context: ContactEmailContext): string[] {
  return cleanTopics(context.candidate.research_topics, context.candidate.mentor_name);
}

function direction(context: ContactEmailContext): string {
  const cleaned = topics(context);
  return cleaned.slice(0, 4).join('、')
    || context.memoryCore.slice(0, 4).join('、')
    || '【研究方向】';
}

function publication(context: ContactEmailContext): string {
  const fromPapers = context.papers[0] || '';
  const fromCandidate = String(context.candidate.publications?.[0] ?? '');
  return stripEnumeratedPrefix(fromPapers || fromCandidate) || '';
}

function teacher(context: ContactEmailContext): string {
  return `${context.candidate.mentor_name}老师`;
}

function department(context: ContactEmailContext): string {
  return String(context.candidate.department ?? '').trim() || '【院系/课题组】';
}

function school(context: ContactEmailContext): string {
  return valueOr(context, 'school') || '【学校】';
}

function gradeMajor(context: ContactEmailContext): string {
  const grade = valueOr(context, 'grade') || '【年级】';
  const major = valueOr(context, 'major') || '【专业】';
  return `${school(context)} ${grade} ${major}`;
}

function subject(context: ContactEmailContext, keyword: string): string {
  const identity = name(context);
  const background = gradeMajor(context);
  return `${keyword}——${identity}（${background}）`;
}

function emailFooter(context: ContactEmailContext): string[] {
  return [
    '此致',
    '敬礼',
    '',
    `学生：${name(context)}`,
    '【日期，如 2026年9月X日】',
  ];
}

function commonEnding(context: ContactEmailContext): string[] {
  return [
    '最后再次感谢老师阅信，殷切期盼老师的回复。祝您身体健康，工作顺利！',
    ...emailFooter(context),
  ];
}

function attachmentLine(): string {
  return '我已将【简历、成绩单、成绩排名证明】上传至附件，如老师需要其他材料，我可随时补充。联系方式：【电话/邮箱】，也很愿意到您办公室当面汇报。';
}

function academicBase(context: ContactEmailContext): string {
  const skills = phraseList(context.profile.skills, 6).join('、');
  return [
    '学业方面，我的加权平均绩点为【GPA/总分】，专业排名【名次/人数】；',
    '【核心课程1】【核心课程2】【核心课程3】等课程成绩较为突出，已通过大学英语四/六级考试，具备较好的英文文献阅读和论文写作基础。',
    '技能与工具方面，我掌握与本方向相关的【编程语言/实验技能/软件平台/仪器工具等】，并能在科研中熟练使用。',
    skills ? `我已有的技能包括：${skills}。` : '',
  ].filter(Boolean).join('');
}

function experienceLines(): string[] {
  return [
    '本科期间，我主要完成了【项目/课程设计名称】，承担【具体分工】，例如【一句具体做法或结果】；',
    '参与过【大创/学科竞赛】，获得【奖项名称】。在这些实践中，我体会到从问题到方案再到实现的完整过程，也认识到自己仍有不足。',
  ];
}

function qualityLine(): string {
  return '我曾担任【班级/社团职务】，具备一定的组织与沟通能力；同时我也是一个【自主学习能力较强/有明确目标/执行力强】的人。';
}

function shortPersonalSummary(context: ContactEmailContext): string {
  return [
    ...experienceLines(),
    qualityLine(),
    '本科期间的经历让我明确希望沿着【老师研究方向】继续深入，也做好了从基础工作学起的准备。',
  ].join('');
}

function render(
  context: ContactEmailContext,
  subjectLine: string,
  opening: string[],
  body: string[],
): { subject: string; body: string } {
  const paragraphs = [
    `尊敬的${teacher(context)}：`,
    '您好！感谢您在百忙之中阅读我的邮件。',
    ...opening,
    ...body,
    attachmentLine(),
    ...commonEnding(context),
  ];
  return {
    subject: subjectLine,
    body: paragraphs.filter((item, index, all) => Boolean(item) && (item.trim() || all[index - 1] !== '')).join('\n\n'),
  };
}

function renderPostgraduate(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `咨询${direction(context)}方向研究生名额`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生，目前正在积极准备推免。通过学院主页和相关论文，我了解到${teacher(context)}长期从事${direction(context)}的研究，尤其在【具体子方向/代表性工作】方面有深入研究。`,
    ],
    [
      academicBase(context),
      ...experienceLines(),
      qualityLine(),
      `我深知自己与${teacher(context)}课题组的要求还有差距，但愿意在正式进入课题前先补齐文献和技能，从基础性工作做起，认真参与组会，及时向老师和师兄师姐请教。`,
      `因此冒昧想请教老师：您今年是否还有研究生名额？我十分期待能够跟随${teacher(context)}在研究生阶段继续学习${direction(context)}方向。`,
    ],
  );
}

function renderStrongResearch(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `基于科研经历申请加入${teacher(context)}课题组`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生。本科期间我参与过【科研项目/竞赛】，因此对研究过程并不陌生。认真了解${teacher(context)}在${direction(context)}方面的工作后，我非常希望能进入您的课题组接受进一步训练。`,
    ],
    [
      '我在项目中主要负责【具体工作】，完成过【方法与结果】；这段经历让我初步掌握了【文献调研/实验/代码/数据分析】等能力。',
      academicBase(context),
      ...experienceLines(),
      qualityLine(),
      `相比${teacher(context)}课题组的要求，我仍有不足，但我的项目经历让我能够较快进入状态，也愿意在正式科研中从文献复现和基础任务做起。`,
      `不知${teacher(context)}今年是否还有研究生或科研实践名额？如能加入您的课题组，我将以认真、严谨的态度完成每一项任务。`,
    ],
  );
}

function renderStrongGpa(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `申请科研实践入门机会`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生，目前 GPA/排名为【___】。我系统学习过【相关课程】，成绩较为扎实，但还没有真正进入过课题组，因此希望通过科研实践补上从课堂到研究这一步。`,
    ],
    [
      academicBase(context),
      '虽然没有完整课题经历，但我的课程设计和自学项目包括【列举相关课程设计/小项目】。这些训练让我养成了严谨、自主的学习习惯。',
      qualityLine(),
      `我非常认同${teacher(context)}在${direction(context)}方向的研究思路，也愿意从文献整理、辅助实验/数据分析等基础工作开始，认真参加组会，配合团队安排。`,
      `如果${teacher(context)}愿意给我一个机会，我会用实际表现证明自己的投入。不知老师近期是否方便接收本科生科研实践？`,
    ],
  );
}

function renderPaperReader(context: ContactEmailContext) {
  const paper = publication(context) || '【论文题目】';
  return render(
    context,
    subject(context, `拜读${teacher(context)}论文后的学习咨询`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生。最近我精读了${teacher(context)}的论文《${paper}》，对其中关于【问题/方法/结论】的讨论印象深刻，也因此想请教一个我思考了很久的问题：【具体问题】。`,
    ],
    [
      '我目前的理解是，论文通过【方法/思路】来处理【难点】，从而得到【结果】；但我还不太明白【某一步】为何这样设计。如果理解有偏差，恳请老师指正。',
      academicBase(context),
      ...experienceLines(),
      qualityLine(),
      `正是这篇论文，让我非常希望能进入${teacher(context)}课题组，围绕${direction(context)}系统学习。我愿意从复现论文、精读参考文献等工作开始，逐步掌握研究方法。`,
      `不知${teacher(context)}是否方便，我希望能当面请教，并了解今年是否有科研实践或研究生名额。`,
    ],
  );
}

function renderSummer(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `申请暑期科研实践`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生。我希望利用【20XX年X月至X月】的完整时间进入${teacher(context)}课题组进行科研实践。`,
    ],
    [
      academicBase(context),
      '这段时间没有课程冲突，可以全职投入。我愿意先完成文献调研、数据整理、实验辅助等任务，尽快达到能够参与组会讨论的程度。',
      ...experienceLines(),
      qualityLine(),
      `之所以申请进入${teacher(context)}课题组，是因为我希望通过一段真实的科研训练判断自己是否适合在${direction(context)}方向继续深造。`,
      `如果老师方便，希望能告知暑期进组前需要我预先补哪些内容。同时冒昧请教今年是否有本科生科研实践名额？`,
    ],
  );
}

function renderThesis(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `本科毕业设计进组申请`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生，预计于【20XX年X月】开始毕业设计选题。我非常希望能进入${teacher(context)}课题组，在您指导下围绕${direction(context)}完成本科毕业设计。`,
    ],
    [
      academicBase(context),
      `通过阅读${teacher(context)}课题组的主页和相关论文，我对【具体切入点】尤其感兴趣。若能把本科毕设与${direction(context)}方向结合，我会非常珍惜这次机会。`,
      ...experienceLines(),
      qualityLine(),
      '我希望毕业设计不是“做完拿学分”，而是能够踏实解决一个小问题，为将来可能的深造打下基础。',
      `不知${teacher(context)}是否愿意接收我做毕业设计？如果您的学生有合适的子课题可以让我参与，我也非常乐意配合。`,
    ],
  );
}

function renderCrossMajor(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `跨专业申请进入${teacher(context)}课题组`),
    [
      `我是${name(context)}，目前主修【原专业】。之所以联系${teacher(context)}，是因为我在学习/项目中接触到${direction(context)}，发现自己真正希望投入的方向是您所从事的研究。`,
    ],
    [
      '为此我自学了【相关课程/技能】，也阅读了您关于【具体方向】的论文和介绍。虽然专业跨度较大，但我在【可迁移能力：数学/编程/实验/信息检索】方面有一定基础，也做好了重新补课的准备。',
      academicBase(context),
      ...experienceLines(),
      qualityLine(),
      `我特别希望进入${teacher(context)}课题组，从基础工作做起，用一到两个学期缩小与团队要求的差距。我也愿意先与老师或您的学生交流，确认自己是否适合${direction(context)}方向。`,
      `不知${teacher(context)}是否愿意考虑跨专业学生参与科研实践或研究生学习？若老师需要，我可以额外提供【原专业成绩单/自学证明/项目材料】。`,
    ],
  );
}

function renderLimitedInfo(context: ContactEmailContext) {
  return render(
    context,
    subject(context, `咨询${direction(context)}方向科研实践机会`),
    [
      `我是${name(context)}，是${gradeMajor(context)}本科生。通过学院官网和您公开发布的信息，我了解到${teacher(context)}长期从事${direction(context)}研究。由于公开资料有限，我不敢贸然说自己已经理解您的全部工作，但这一方向与我的兴趣和规划高度契合。`,
    ],
    [
      academicBase(context),
      ...experienceLines(),
      qualityLine(),
      `我尤其希望学习${direction(context)}中【希望补充的部分】。如果${teacher(context)}时间允许，我希望能向您请教：进入这一方向前，最适合我先补哪些课程和文献。`,
      `无论是否方便接收我，都非常感谢${teacher(context)}阅读这封信。我冒昧询问今年是否有科研实践或研究生名额，期待能有机会向老师请教。`,
    ],
  );
}

export function buildScenarioEmail(
  scenario: EmailScenarioId,
  context: ContactEmailContext,
): { subject: string; body: string } {
  switch (scenario) {
    case 'strong_research':
      return renderStrongResearch(context);
    case 'strong_gpa':
      return renderStrongGpa(context);
    case 'paper_reader':
      return renderPaperReader(context);
    case 'summer':
      return renderSummer(context);
    case 'thesis':
      return renderThesis(context);
    case 'cross_major':
      return renderCrossMajor(context);
    case 'limited_info':
      return renderLimitedInfo(context);
    case 'postgraduate':
    default:
      return renderPostgraduate(context);
  }
}
