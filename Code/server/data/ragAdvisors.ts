/**
 * 真实 RAG 导师数据接入（D 侧 service 层映射）。
 *
 * 读取 C 产出的 `paper-claw-master/data/ustc_mentor_rag.json`（完整进仓：972 导师 / 1969 证据），
 * 把 `CandidateMentor` 结构映射为前端契约 `AdvisorDetail`。
 *
 * 协作铁律：真实字段与前端契约不符时在 D 的 service/server 层做映射，不改 A/C 输出格式、
 * 不改前端组件。此模块正是该条的应用——替代原 `stub/advisors.ts` 的 `'1'..'8'` 假数据，
 * 让真实检索结果（id = candidate_id，如 `ustc_faculty_26275`）能点进详情、发邮件、被推荐。
 *
 * 映射说明：
 * - id           candidate_id
 * - name         mentor_name
 * - title        source_metadata.academic_title（职称）
 * - department   department
 * - tags         research_topics
 * - papers       source_metadata.publication_total_count（缺失时回退代表作数量）
 * - matchScore   详情页无动态匹配值，缺省 0（真实匹配分仅在检索时由 A 计算）
 * - bio          由证据 extracted_fact / mentor_role / affiliation 拼接
 * - contact      homepage（RAG 无邮箱，给出主页作为唯一官方联系方式）
 * - recentPapers publications（标题列表，年份/venue 缺失）
 * - recruiting   recruitment_status（可能为 null）
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { cleanTopics } from './topicBoilerplate';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export interface RagMentor {
  candidate_id: string;
  mentor_name: string;
  affiliation?: string;
  department?: string;
  research_topics?: string[];
  methods?: string[];
  publications?: string[];
  projects?: string[];
  homepage?: string;
  recruitment_status?: string | null;
  evidence_refs?: string[];
  missing_fields?: string[];
  source_metadata?: {
    ustc_faculty_id?: string;
    english_name?: string;
    academic_title?: string;
    mentor_role?: string;
    paper_platforms?: string;
    profile_bio?: string;
    profile_email?: string;
    profile_office?: string;
    profile_graduated_from?: string;
    topics_source?: number;
    representative_publication_count?: number;
    publication_total_count?: number;
    publication_count_source?: string;
    methods_verified?: boolean;
    paper_identity_verified?: boolean;
    pending_paper_platforms?: string;
    topics_extracted_count?: number;
    topics_truncated?: boolean;
  };
}

export interface RagEvidence {
  evidence_id: string;
  candidate_id: string;
  source_type?: string;
  source_uri?: string;
  title?: string;
  extracted_fact?: string;
  locator?: string;
  retrieved_at?: string;
  freshness?: string;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

class RagAdvisorStore {
  private candidates: RagMentor[] = [];
  private evidence: RagEvidence[] = [];
  private byId = new Map<string, RagMentor>();
  private loadedPath = '';
  private loadError: string | null = null;

  constructor() {
    this.load();
  }

  private resolvePath(): string | null {
    // 从 server/data 向上找到仓库根的 paper-claw-master/data/ustc_mentor_rag.json
    const candidates = [
      path.join(__dirname, '..', '..', '..', '..', 'paper-claw-master', 'data', 'ustc_mentor_rag.json'),
      path.join(__dirname, '..', '..', '..', 'paper-claw-master', 'data', 'ustc_mentor_rag.json'),
      path.join(__dirname, '..', '..', 'paper-claw-master', 'data', 'ustc_mentor_rag.json'),
      path.join(__dirname, '..', '..', '..', '..', '..', 'paper-claw-master', 'data', 'ustc_mentor_rag.json'),
    ];
    for (const p of candidates) {
      try {
        if (fs.existsSync(p)) return fs.realpathSync(p);
      } catch {
        /* 继续找下一个 */
      }
    }
    return null;
  }

  private load(): void {
    const p = this.resolvePath();
    if (!p) {
      this.loadError = 'RAG 数据文件不存在（paper-claw-master/data/ustc_mentor_rag.json）';
      return;
    }
    try {
      const raw = JSON.parse(fs.readFileSync(p, 'utf-8'));
      this.candidates = (Array.isArray(raw.candidates) ? raw.candidates : []).map(
        (item: RagMentor) => ({
          ...item,
          research_topics: cleanTopics(item?.research_topics, item?.mentor_name),
        }),
      );
      this.evidence = Array.isArray(raw.evidence) ? raw.evidence : [];
      this.loadedPath = p;
      for (const c of this.candidates) {
        if (c && c.candidate_id) this.byId.set(c.candidate_id, c);
      }
    } catch (err) {
      this.loadError = `解析 RAG 数据失败: ${err instanceof Error ? err.message : String(err)}`;
    }
  }

  getCandidates(): RagMentor[] {
    return this.candidates;
  }

  getById(id: string): RagMentor | undefined {
    return this.byId.get(id);
  }

  /** 取某候选绑定的证据（用于简介与联系方式摘要） */
  getEvidenceFor(candidateId: string): RagEvidence[] {
    return this.evidence.filter((e) => e.candidate_id === candidateId);
  }

  get loadFailed(): boolean {
    return this.loadError !== null;
  }

  get errorMessage(): string | null {
    return this.loadError;
  }

  get sourcePath(): string {
    return this.loadedPath;
  }
}

/** 单例，进程生命周期内缓存一次 */
const store = new RagAdvisorStore();

/** 由 RAG 候选拼出前端 AdvisorDetail（D 侧映射） */
export function toAdvisorDetail(c: RagMentor): {
  id: string;
  name: string;
  title: string;
  department: string;
  tags: string[];
  hIndex?: number;
  papers: number;
  matchScore: number;
  explanation?: string;
  bio?: string;
  contact?: string;
  recruiting?: string;
  recentPapers?: { title: string; year?: number; venue?: string }[];
} {
  const topics = cleanTopics(c.research_topics, c.mentor_name);
  const evidence = store.getEvidenceFor(c.candidate_id);
  // build_rag 只把 author_match_status=confirmed 的代表论文写入 candidate；待审核
  // 论文仅留在 evidence，不进入这里。publication_total_count 是论文平台给出的作者
  // 总作品数，和 publications.length（入库代表作数）是两个不同口径。
  const pubs = Array.isArray(c.publications) ? c.publications : [];
  const sourceTotal = Number(c.source_metadata?.publication_total_count);
  const paperCount = Number.isFinite(sourceTotal) && sourceTotal >= 0
    ? sourceTotal : pubs.length;

  // 优先用 RAG 里从官网个人主页抽出的 bio（build_rag.py 的 profile_bio），
  // 缺失时回退到「身份/角色 + 方向」拼接的兜底简介。
  let bio: string | undefined;
  if (c.source_metadata?.profile_bio) {
    bio = c.source_metadata.profile_bio.trim();
  } else {
    const bioParts: string[] = [];
    const role = c.source_metadata?.mentor_role;
    if (role) bioParts.push(`${c.mentor_name}，${role}。`);
    for (const ev of evidence) {
      if (ev.extracted_fact && ev.source_type?.startsWith('ustc_official_faculty_profile')) {
        bioParts.push(ev.extracted_fact);
      }
    }
    if (topics.length > 0 && !bioParts.some((b) => topics.some((t) => b.includes(t)))) {
      bioParts.push(`主要研究方向：${topics.join('；')}。`);
    }
    bio = bioParts.length > 0 ? bioParts.join('\n') : undefined;
  }

  // contact：优先邮箱（官网抽出的 profile_email），其次主页 URL。
  const contact = c.source_metadata?.profile_email || c.homepage || undefined;

  return {
    id: c.candidate_id,
    name: c.mentor_name,
    title: c.source_metadata?.academic_title ?? '',
    department: c.department ?? '',
    tags: topics,
    papers: paperCount,
    matchScore: 0,
    bio,
    contact,
    recruiting: c.recruitment_status || undefined,
    recentPapers: pubs.slice(0, 20).map((title) => ({ title })),
  };
}

/** 精简为前端检索用的 Advisor（无详情扩展字段，匹配分留空由调用方补） */
export function toLightAdvisor(c: RagMentor): {
  id: string;
  name: string;
  title: string;
  department: string;
  tags: string[];
  hIndex?: number;
  papers: number;
  matchScore: number;
} {
  const pubs = Array.isArray(c.publications) ? c.publications : [];
  const sourceTotal = Number(c.source_metadata?.publication_total_count);
  return {
    id: c.candidate_id,
    name: c.mentor_name,
    title: c.source_metadata?.academic_title ?? '',
    department: c.department ?? '',
    tags: cleanTopics(c.research_topics, c.mentor_name),
    papers: Number.isFinite(sourceTotal) && sourceTotal >= 0 ? sourceTotal : pubs.length,
    matchScore: 0,
  };
}

export { store as ragStore };
export const ragData = {
  get candidates(): RagMentor[] {
    return store.getCandidates();
  },
  get isReady(): boolean {
    return !store.loadFailed && store.getCandidates().length > 0;
  },
  get errorMessage(): string | null {
    return store.errorMessage;
  },
  get sourcePath(): string {
    return store.sourcePath;
  },
};
