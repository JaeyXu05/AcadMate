import type { RunEventRead, RunRead } from '../../api/types';
import { StatusBadge } from '../../components/StatusBadge';

interface AgentActivityProps {
  run: RunRead;
}

interface ActivityStats {
  toolCalls: number;
  searchSessions: number;
  errors: number;
  warnings: number;
}

export function AgentActivity({ run }: AgentActivityProps) {
  const stats = activityStats(run.events);
  const summary = [
    `${run.events.length} events`,
    `${stats.toolCalls} tools`,
    `${stats.searchSessions} search`,
    `${stats.errors} errors`,
  ].join(' · ');
  const lines = activityLines(run);

  return (
    <details className="agent-activity">
      <summary>
        <span>Agent Activity</span>
        <StatusBadge status={run.status} />
        <span>{summary}</span>
      </summary>
      <div className="agent-activity__body">
        {run.error_message && <p className="agent-activity__error">{run.error_message}</p>}
        <div className="agent-activity__metrics">
          <span>{run.workflow}</span>
          <span>run #{run.id}</span>
          {stats.warnings > 0 && <span>{stats.warnings} warnings</span>}
        </div>
        <div className="agent-activity__events">
          {lines.map((line) => (
            <div className={`agent-activity__event agent-activity__event--${line.level}`} key={`${line.sequence}-${line.label}`}>
              <span>#{line.sequence}</span>
              <strong>{line.label}</strong>
              {line.detail && <span>{line.detail}</span>}
            </div>
          ))}
        </div>
        <details className="agent-activity__raw">
          <summary>Show raw</summary>
          <pre>{JSON.stringify(run.events, null, 2)}</pre>
        </details>
      </div>
    </details>
  );
}

function activityStats(events: RunEventRead[]): ActivityStats {
  const toolCallIds = new Set<string>();
  const searchSessionIds = new Set<string>();
  let errors = 0;
  let warnings = 0;

  for (const event of events) {
    if (event.level === 'error' || event.event_type.includes('failed')) {
      errors += 1;
    }
    if (event.level === 'warning') {
      warnings += 1;
    }
    if (event.event_type.startsWith('agent_tool_call')) {
      const id = event.payload.tool_call_id;
      toolCallIds.add(id == null ? String(event.sequence) : String(id));
    }
    const searchSessionId = event.payload.search_session_id;
    if (searchSessionId != null) {
      searchSessionIds.add(String(searchSessionId));
    }
  }

  return { toolCalls: toolCallIds.size, searchSessions: searchSessionIds.size, errors, warnings };
}

function activityLines(run: RunRead) {
  const events = run.events.length ? run.events : [];
  return events.map((event) => ({
    sequence: event.sequence,
    level: event.level,
    label: eventLabel(event),
    detail: eventDetail(event),
  }));
}

function eventLabel(event: RunEventRead): string {
  switch (event.event_type) {
    case 'agent_message_received':
      return 'Message received';
    case 'agent_message_completed':
      return 'Response completed';
    case 'agent_message_failed':
      return 'Response failed';
    case 'agent_stream_update':
      return 'Agent update';
    case 'agent_interrupt_requested':
      return 'Waiting for user decision';
    case 'agent_resume_requested':
      return 'Run resume requested';
    case 'agent_tool_call_started':
      return `Tool started${toolName(event)}`;
    case 'agent_tool_call_completed':
      return `Tool completed${toolName(event)}`;
    case 'agent_tool_call_failed':
      return `Tool failed${toolName(event)}`;
    case 'approval_decision':
      return 'Approval decision';
    case 'agent_run_cancelled':
      return 'Run cancelled';
    default:
      return event.event_type.replace(/_/g, ' ');
  }
}

function eventDetail(event: RunEventRead): string | null {
  const payload = event.payload;
  if (typeof payload.error === 'string') {
    return payload.error;
  }
  if (typeof payload.result_preview === 'string') {
    return payload.result_preview;
  }
  if (typeof payload.decision === 'string') {
    return payload.decision;
  }
  if (Array.isArray(payload.action_requests)) {
    return `${payload.action_requests.length} action${payload.action_requests.length === 1 ? '' : 's'}`;
  }
  if (Array.isArray(payload.decisions)) {
    return `${payload.decisions.length} decision${payload.decisions.length === 1 ? '' : 's'}`;
  }
  if (typeof payload.query_text === 'string') {
    return payload.query_text;
  }
  if (payload.search_session_id != null) {
    return `search session #${String(payload.search_session_id)}`;
  }
  if (payload.assistant_message_id != null) {
    return `assistant message #${String(payload.assistant_message_id)}`;
  }
  const data = payload.data;
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const keys = Object.keys(data).slice(0, 4);
    if (keys.length) {
      return keys.join(', ');
    }
  }
  if (typeof payload.status === 'string') {
    return payload.status;
  }
  return null;
}

function toolName(event: RunEventRead): string {
  return typeof event.payload.tool_name === 'string' ? ` · ${event.payload.tool_name}` : '';
}
