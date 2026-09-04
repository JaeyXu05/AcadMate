import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface RetrievalFamilyPolicy {
  id: string;
  aliases: string[];
  children?: string[];
  parents?: string[];
  preserve?: string[];
  canonical?: string;
}

export interface RetrievalPolicy {
  version: number;
  scores: {
    relevance_threshold: number;
    topic_calibration: number;
    untrusted_topic_factor: number;
    fallback_factor: number;
    direct_relation: number;
    adjacent_relation: number;
  };
  query_contract: {
    default_logic: 'AND' | 'OR';
    explicit_or_tokens: string[];
    explicit_and_tokens: string[];
  };
  concept_families: RetrievalFamilyPolicy[];
}

const moduleDir = dirname(fileURLToPath(import.meta.url));
const policyPath = resolve(moduleDir, '../../../paper-claw-master/config/retrieval_policy.v3.json');

export const retrievalPolicy = JSON.parse(readFileSync(policyPath, 'utf8')) as RetrievalPolicy;

if (retrievalPolicy.version !== 3) {
  throw new Error(`Unsupported retrieval policy version: ${retrievalPolicy.version}`);
}
