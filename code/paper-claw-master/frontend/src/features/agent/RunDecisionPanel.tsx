import { useState } from 'react';
import { api } from '../../api/client';
import type { JsonValue, RunDecision, RunDecisionType, RunRead } from '../../api/types';
import { ErrorBanner } from '../../components/ErrorBanner';
import { StatusBadge } from '../../components/StatusBadge';

interface RunDecisionPanelProps {
  run: RunRead | null;
  onRefresh: () => void;
}

interface ActionRequest {
  name?: string;
  args?: Record<string, unknown>;
  description?: string;
}

interface ReviewConfig {
  allowed_decisions?: RunDecisionType[];
  [key: string]: unknown;
}

export function RunDecisionPanel({ run, onRefresh }: RunDecisionPanelProps) {
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedArgsByIndex, setEditedArgsByIndex] = useState<Record<number, string>>({});
  const [jsonErrorsByIndex, setJsonErrorsByIndex] = useState<Record<number, string | null>>({});
  const interrupt = latestInterrupt(run);
  const actions = interrupt?.actionRequests ?? [];
  const reviews = interrupt?.reviewConfigs ?? [];
  const actionCountLabel = `${actions.length} action${actions.length === 1 ? '' : 's'}`;
  const canApprove = canSubmit(actions, reviews, 'approve');
  const canEdit = canSubmit(actions, reviews, 'edit');
  const canReject = canSubmit(actions, reviews, 'reject');
  const hasMixedDecisionRules = actions.length > 1 && new Set(actions.map((_, index) => allowedDecisions(reviews[index]).join('|'))).size > 1;
  const hasJsonErrors = Object.values(jsonErrorsByIndex).some(Boolean);

  const submitDecision = async (decision: Extract<RunDecisionType, 'approve' | 'reject'>) => {
    if (!run || !canSubmit(actions, reviews, decision)) {
      setError(`${formatAllowedDecision(decision)} is not allowed for every requested action.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.submitRunApproval(run.id, {
        decisions: actions.map((action, index) => buildDecisionPayload(decision, action, reviews[index], comment)),
        comment: comment || null,
      });
      resetForm();
      onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Decision failed');
    } finally {
      setSubmitting(false);
    }
  };

  const enterEditMode = () => {
    if (!canEdit) {
      setError('Edit is not allowed for every requested action.');
      return;
    }
    setEditedArgsByIndex(Object.fromEntries(actions.map((action, index) => [index, JSON.stringify(action.args ?? {}, null, 2)])));
    setJsonErrorsByIndex({});
    setIsEditing(true);
    setError(null);
  };

  const updateEditedArgs = (index: number, value: string) => {
    setEditedArgsByIndex((current) => ({ ...current, [index]: value }));
    const parsed = parseJsonRecord(value);
    setJsonErrorsByIndex((current) => ({ ...current, [index]: parsed.error }));
  };

  const submitEditedDecision = async () => {
    if (!run || !canEdit) {
      setError('Edit is not allowed for every requested action.');
      return;
    }
    const parsedArgs: Record<number, Record<string, unknown>> = {};
    const nextErrors: Record<number, string | null> = {};
    actions.forEach((_, index) => {
      const parsed = parseJsonRecord(editedArgsByIndex[index] ?? '{}');
      nextErrors[index] = parsed.error;
      if (parsed.value) {
        parsedArgs[index] = parsed.value;
      }
    });
    setJsonErrorsByIndex(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) {
      setError('Fix invalid JSON before submitting edited arguments.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.submitRunApproval(run.id, {
        decisions: actions.map((action, index) => buildDecisionPayload('edit', action, reviews[index], comment, parsedArgs[index])),
        comment: comment || null,
      });
      resetForm();
      onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Decision failed');
    } finally {
      setSubmitting(false);
    }
  };

  const resetForm = () => {
    setComment('');
    setIsEditing(false);
    setEditedArgsByIndex({});
    setJsonErrorsByIndex({});
  };

  return (
    <section className="panel run-decision-panel">
      <div className="panel-header">
        <p className="eyebrow">Human approval required</p>
        <h2>{actions.length === 1 ? 'Review requested tool call' : 'Review requested tool calls'}</h2>
      </div>
      <div className="panel-body stack">
        <ErrorBanner message={error} />
        {run && (
          <>
            <div className="run-decision-panel__summary">
              <span>run #{run.id}</span>
              <StatusBadge status={run.status} />
              <span>{actionCountLabel}</span>
            </div>
            {hasMixedDecisionRules && (
              <p className="meta-row">This approval request contains mixed decision rules; only decisions allowed for every action are enabled.</p>
            )}
            {actions.length > 0 ? (
              <div className="stack">
                {actions.map((action, index) => {
                  const decisions = allowedDecisions(reviews[index]);
                  return (
                    <article className="run-decision-card" key={`${action.name ?? 'action'}-${index}`}>
                      <div className="run-decision-card__header">
                        <div>
                          <span className="run-decision-card__label">Tool request</span>
                          <strong className="run-decision-card__tool">{friendlyToolName(action.name)}</strong>
                          {action.name && action.name !== friendlyToolName(action.name) && <span className="run-decision-card__raw-name">{action.name}</span>}
                        </div>
                        <div className="decision-chip-row" aria-label="Allowed decisions">
                          {decisions.map((decision) => (
                            <span className={`decision-chip decision-chip--${decision}`} key={decision}>{formatAllowedDecision(decision)}</span>
                          ))}
                        </div>
                      </div>
                      {action.description && <p className="run-decision-card__description">{action.description}</p>}
                      {renderActionSummary(action)}
                      {isEditing && canEdit && (
                        <label className="json-editor">
                          Edited arguments for action {index + 1}
                          <textarea
                            value={editedArgsByIndex[index] ?? JSON.stringify(action.args ?? {}, null, 2)}
                            onChange={(event) => updateEditedArgs(index, event.target.value)}
                            spellCheck={false}
                          />
                          {jsonErrorsByIndex[index] && <span className="json-error">{jsonErrorsByIndex[index]}</span>}
                        </label>
                      )}
                      {action.args && (
                        <details className="raw-json-details">
                          <summary>Raw tool arguments</summary>
                          <pre>{JSON.stringify(action.args, null, 2)}</pre>
                        </details>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="meta-row">This run is waiting for a decision, but no action details were provided.</p>
            )}
            <label>
              Decision note
              <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Optional note for the run event" />
            </label>
            <div className="button-row">
              {isEditing ? (
                <>
                  <button className="primary-button" disabled={submitting || !canEdit || hasJsonErrors} onClick={submitEditedDecision}>Submit edited arguments</button>
                  <button className="secondary-button" disabled={submitting} onClick={() => setIsEditing(false)}>Cancel edit</button>
                  <button className="danger-button" disabled={submitting || !canReject} onClick={() => submitDecision('reject')}>Reject request</button>
                </>
              ) : (
                <>
                  <button className="primary-button" disabled={submitting || !canApprove} onClick={() => submitDecision('approve')}>Approve as shown</button>
                  {canEdit && <button className="secondary-button" disabled={submitting} onClick={enterEditMode}>Edit arguments</button>}
                  <button className="danger-button" disabled={submitting || !canReject} onClick={() => submitDecision('reject')}>Reject request</button>
                </>
              )}
            </div>
            <p className="meta-row">Decisions are submitted in the order requested by the agent.</p>
          </>
        )}
      </div>
    </section>
  );
}

function latestInterrupt(run: RunRead | null): { actionRequests: ActionRequest[]; reviewConfigs: ReviewConfig[] } | null {
  const event = [...(run?.events ?? [])].reverse().find((item) => item.event_type === 'agent_interrupt_requested');
  if (!event) {
    return null;
  }
  return {
    actionRequests: asObjectArray(event.payload.action_requests).map((item) => ({
      name: typeof item.name === 'string' ? item.name : undefined,
      args: asRecord(item.args),
      description: typeof item.description === 'string' ? item.description : undefined,
    })),
    reviewConfigs: asObjectArray(event.payload.review_configs).map((item) => ({
      ...item,
      allowed_decisions: asDecisionArray(item.allowed_decisions),
    })),
  };
}

function buildDecisionPayload(
  type: RunDecisionType,
  action: ActionRequest,
  review: ReviewConfig | undefined,
  comment: string,
  editedArgs?: Record<string, unknown>,
): RunDecision {
  if (!allowedDecisions(review).includes(type)) {
    throw new Error(`${formatAllowedDecision(type)} is not allowed for this action.`);
  }
  if (type === 'edit') {
    return { type, edited_action: { name: action.name ?? '', args: editedArgs ?? {} } };
  }
  if (type === 'reject') {
    return { type, message: comment || undefined };
  }
  if (type === 'respond') {
    return { type, message: comment || '' };
  }
  return { type };
}

function canSubmit(actions: ActionRequest[], reviews: ReviewConfig[], decision: RunDecisionType): boolean {
  if (!actions.length) {
    return false;
  }
  return actions.every((_, index) => allowedDecisions(reviews[index]).includes(decision));
}

function allowedDecisions(review: ReviewConfig | undefined): RunDecisionType[] {
  return review?.allowed_decisions?.length ? review.allowed_decisions : ['approve', 'reject'];
}

function friendlyToolName(name?: string): string {
  if (name === 'update_paper_metadata') {
    return 'Update paper metadata';
  }
  return name ? name.split('_').join(' ') : 'Requested action';
}

function formatAllowedDecision(decision: RunDecisionType): string {
  if (decision === 'approve') {
    return 'Approve';
  }
  if (decision === 'edit') {
    return 'Edit';
  }
  if (decision === 'reject') {
    return 'Reject';
  }
  return 'Respond';
}

function renderActionSummary(action: ActionRequest) {
  if (action.name === 'update_paper_metadata') {
    return renderMetadataSummary(action.args);
  }
  return renderGenericSummary(action.args);
}

function renderMetadataSummary(args: Record<string, unknown> | undefined) {
  const metadata = asRecord(args?.metadata);
  const identifiers = asObjectArray(args?.identifiers);
  const sourceRecords = asObjectArray(args?.source_records);
  return (
    <div className="tool-args-summary">
      <div className="tool-args-grid">
        <ArgSection title="Paper" items={[['paper_id', formatValue(args?.paper_id)]]} />
        <ArgSection title="Reason" items={[['reason', formatValue(args?.reason)]]} />
        <ArgSection title="Metadata fields" items={metadata ? Object.entries(metadata).map(([key, value]) => [key, formatValue(value)]) : []} emptyLabel="No direct paper fields" />
        <ArgSection
          title="Identifiers"
          items={identifiers.map((item, index) => [
            `#${index + 1}`,
            `${formatValue(item.identifier_type ?? item.type)}: ${formatValue(item.identifier_value ?? item.value)}`,
          ])}
          emptyLabel="No identifiers"
        />
        <ArgSection
          title="Source records"
          items={sourceRecords.map((item, index) => [
            `#${index + 1}`,
            summarizeSourceRecord(item),
          ])}
          emptyLabel="No source records"
        />
      </div>
    </div>
  );
}

function renderGenericSummary(args: Record<string, unknown> | undefined) {
  const entries = args ? Object.entries(args).map(([key, value]) => [key, formatValue(value)] as [string, string]) : [];
  return (
    <div className="tool-args-summary">
      <ArgSection title="Arguments" items={entries} emptyLabel="No arguments" />
    </div>
  );
}

function ArgSection({ title, items, emptyLabel = 'None' }: { title: string; items: [string, string][]; emptyLabel?: string }) {
  return (
    <section className="tool-args-section">
      <h3>{title}</h3>
      {items.length ? (
        <dl>
          {items.map(([key, value]) => (
            <div key={`${title}-${key}`}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>{emptyLabel}</p>
      )}
    </section>
  );
}

function summarizeSourceRecord(record: Record<string, unknown>): string {
  const parts = [
    formatValue(record.source),
    formatValue(record.source_record_id ?? record.arxiv_id ?? record.openalex_id),
    formatValue(record.source_url ?? record.url ?? record.pdf_url),
  ].filter((item) => item !== '—');
  return parts.length ? parts.join(' · ') : formatValue(record);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(formatValue).join(', ');
  }
  return JSON.stringify(value);
}

function parseJsonRecord(value: string): { value?: Record<string, unknown>; error: string | null } {
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { error: 'Arguments must be a JSON object.' };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch (caught) {
    return { error: caught instanceof Error ? caught.message : 'Invalid JSON.' };
  }
}

function asObjectArray(value: JsonValue | unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : [];
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function asDecisionArray(value: unknown): RunDecisionType[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  return value.filter((item): item is RunDecisionType => item === 'approve' || item === 'edit' || item === 'reject' || item === 'respond');
}
