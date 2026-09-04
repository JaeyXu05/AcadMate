import fs from 'node:fs';

const [ragPath, cloudPath] = process.argv.slice(2);

function fail(message) {
  console.error(`[ERROR] ${message}`);
  process.exitCode = 1;
}

try {
  if (!ragPath || !cloudPath) throw new Error('RAG and cloud-data paths are required.');
  const rag = JSON.parse(fs.readFileSync(ragPath, 'utf8'));
  const cloud = JSON.parse(fs.readFileSync(cloudPath, 'utf8'));
  const ragIds = new Set((rag.candidates ?? []).map((item) => String(item?.candidate_id ?? '')).filter(Boolean));
  const cloudIds = new Set((cloud.nodes ?? []).map((item) => String(item?.candidate_id ?? '')).filter(Boolean));
  if (!ragIds.size || !cloudIds.size) throw new Error('RAG or cloud data contains no mentor nodes.');
  const ragOnly = [...ragIds].filter((id) => !cloudIds.has(id));
  const cloudOnly = [...cloudIds].filter((id) => !ragIds.has(id));
  if (ragOnly.length || cloudOnly.length) {
    throw new Error(`candidate_id mismatch: rag-only=${ragOnly.length}, cloud-only=${cloudOnly.length}.`);
  }
  console.log(`[OK] Runtime data is readable: ${ragIds.size} shared mentor IDs.`);
  const ragEvidence = Number(rag.evidence_count ?? rag.evidence?.length ?? 0);
  const cloudEvidence = Number(cloud.meta?.evidence_count ?? 0);
  if (cloudEvidence !== ragEvidence || String(cloud.meta?.generated_at ?? '') < String(rag.generated_at ?? '')) {
    console.warn(`[WARN] Cloud data is older than the RAG or has stale metadata (cloud evidence=${cloudEvidence}, RAG evidence=${ragEvidence}). Rebuild cloud3d/cloud_data.json before release.`);
  }
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}
