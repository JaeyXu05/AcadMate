import api from './axios';

export interface PaperSearchCandidate {
  id: number;
  rank: number;
  source: string;
  paper_id?: number | null;
  title: string;
  abstract?: string | null;
  authors: string[];
  year?: number | null;
  venue?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  openalex_id?: string | null;
  landing_page_url?: string | null;
  pdf_url?: string | null;
  score?: number | null;
  match_reasons?: string[];
}

export interface PaperSearchResponse {
  search_session_id: number;
  source: string;
  mode: string;
  query: string;
  query_used: string;
  status: string;
  warnings: string[];
  candidates: PaperSearchCandidate[];
}

export async function searchPapers(input: { query: string; source?: 'local' | 'arxiv' | 'openalex'; mode?: string; limit?: number }): Promise<PaperSearchResponse> {
  return (await api.get('/papers/search', {
    params: { query: input.query, source: input.source || 'openalex', mode: input.mode || 'keyword', limit: input.limit || 8 },
  })).data;
}

export async function confirmPaperCandidate(searchSessionId: number, candidateId: number): Promise<{ paper_id: number | null; title?: string | null; status: string }> {
  return (await api.post(`/papers/search/${searchSessionId}/confirm`, { candidate_id: candidateId })).data;
}

