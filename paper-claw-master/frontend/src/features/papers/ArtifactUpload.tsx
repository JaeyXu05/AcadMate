import { FormEvent, useState } from 'react';
import { api } from '../../api/client';
import type { ArtifactUploadRole } from '../../api/types';
import { ErrorBanner } from '../../components/ErrorBanner';

interface ArtifactUploadProps {
  paperId: number;
  activeRunId: number | null;
  onUploaded: () => void;
}

export function ArtifactUpload({ paperId, activeRunId, onUploaded }: ArtifactUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [role, setRole] = useState<ArtifactUploadRole>('pdf');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.uploadPaperArtifact(paperId, { file, role, runId: activeRunId });
      setFile(null);
      onUploaded();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Upload failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <ErrorBanner message={error} />
      <label>
        Artifact role
        <select value={role} onChange={(event) => setRole(event.target.value as ArtifactUploadRole)}>
          <option value="pdf">PDF</option>
          <option value="source">Source archive</option>
        </select>
      </label>
      <label>
        File
        <input type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
      </label>
      <button className="primary-button" disabled={!file || submitting} type="submit">
        {submitting ? 'Attaching...' : 'Attach artifact'}
      </button>
    </form>
  );
}
