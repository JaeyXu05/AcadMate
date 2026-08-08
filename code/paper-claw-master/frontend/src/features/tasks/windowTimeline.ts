import type { ArxivTaskQueryWindowRead } from '../../api/types';

const CONNECTED_TOLERANCE_MS = 60_000;

export type WindowTimelineSegment = {
  key: string;
  kind: 'success' | 'issue' | 'gap';
  status: string;
  start: string;
  end: string;
  widthPercent: number;
  fetchedCount: number;
  totalResults: number | null;
  intensity: number;
  windowIds: number[];
  windows: ArxivTaskQueryWindowRead[];
};

export type WindowTimeline = {
  summary: {
    totalWindows: number;
    coverageStart: string | null;
    coverageEnd: string | null;
    issueCount: number;
    successSegmentCount: number;
  };
  segments: WindowTimelineSegment[];
  details: ArxivTaskQueryWindowRead[];
};

export function buildWindowTimeline(windows: ArxivTaskQueryWindowRead[]): WindowTimeline {
  const visibleWindows = selectVisibleWindows(windows);
  const sorted = [...visibleWindows].sort((left, right) => Date.parse(left.window_start) - Date.parse(right.window_start));
  if (!sorted.length) {
    return {
      summary: { totalWindows: 0, coverageStart: null, coverageEnd: null, issueCount: 0, successSegmentCount: 0 },
      segments: [],
      details: [],
    };
  }

  const segments: WindowTimelineSegment[] = [];
  for (const window of sorted) {
    const previous = segments[segments.length - 1];
    if (previous && Date.parse(window.window_start) > Date.parse(previous.end) + CONNECTED_TOLERANCE_MS) {
      segments.push(newGapSegment(previous.end, window.window_start));
    }
    if (isSuccessful(window)) {
      const latest = segments[segments.length - 1];
      if (latest?.kind === 'success' && Date.parse(window.window_start) <= Date.parse(latest.end) + CONNECTED_TOLERANCE_MS) {
        latest.end = maxIso(latest.end, window.window_end);
        latest.fetchedCount += window.fetched_count;
        latest.totalResults = sumNullable(latest.totalResults, window.total_results);
        latest.windowIds.push(window.id);
        latest.windows.push(window);
      } else {
        segments.push(newWindowSegment(window, 'success'));
      }
    } else {
      segments.push(newWindowSegment(window, 'issue'));
    }
  }

  const maxFetched = Math.max(1, ...segments.flatMap((segment) => segment.windows.map((window) => window.fetched_count)));
  const timelineStart = Date.parse(sorted[0].window_start);
  const timelineEnd = Math.max(...sorted.map((window) => Date.parse(window.window_end)));
  const timelineDuration = Math.max(1, timelineEnd - timelineStart);
  const normalizedSegments = segments.map((segment) => {
    const peakFetched = Math.max(0, ...segment.windows.map((window) => window.fetched_count));
    return {
      ...segment,
      widthPercent: Math.max(2.5, ((Date.parse(segment.end) - Date.parse(segment.start)) / timelineDuration) * 100),
      intensity: segment.kind === 'gap' ? 0 : round(peakFetched / maxFetched),
    };
  });
  const issueWindows = sorted.filter((window) => !isSuccessful(window));
  const recentWindows = [...sorted].reverse().filter((window) => isSuccessful(window));

  return {
    summary: {
      totalWindows: sorted.length,
      coverageStart: sorted[0].window_start,
      coverageEnd: new Date(timelineEnd).toISOString().replace('.000Z', 'Z'),
      issueCount: issueWindows.length,
      successSegmentCount: normalizedSegments.filter((segment) => segment.kind === 'success').length,
    },
    segments: normalizedSegments,
    details: [...issueWindows, ...recentWindows],
  };
}

function selectVisibleWindows(windows: ArxivTaskQueryWindowRead[]): ArxivTaskQueryWindowRead[] {
  const latestSuccessfulByRange = new Map<string, ArxivTaskQueryWindowRead>();
  for (const window of windows) {
    if (!isSuccessful(window)) {
      continue;
    }
    const key = rangeKey(window);
    const current = latestSuccessfulByRange.get(key);
    if (!current || Date.parse(window.updated_at) > Date.parse(current.updated_at) || (window.updated_at === current.updated_at && window.id > current.id)) {
      latestSuccessfulByRange.set(key, window);
    }
  }
  return windows.filter((window) => {
    if (isSuccessful(window)) {
      return latestSuccessfulByRange.get(rangeKey(window))?.id === window.id;
    }
    return !latestSuccessfulByRange.has(rangeKey(window));
  });
}

function rangeKey(window: ArxivTaskQueryWindowRead): string {
  return `${window.subscription_id}:${window.window_start}:${window.window_end}`;
}

function isSuccessful(window: ArxivTaskQueryWindowRead): boolean {
  return window.status === 'succeeded';
}

function newWindowSegment(window: ArxivTaskQueryWindowRead, kind: 'success' | 'issue'): WindowTimelineSegment {
  return {
    key: `${kind}-${window.id}`,
    kind,
    status: window.status,
    start: window.window_start,
    end: window.window_end,
    widthPercent: 0,
    fetchedCount: window.fetched_count,
    totalResults: window.total_results,
    intensity: 0,
    windowIds: [window.id],
    windows: [window],
  };
}

function newGapSegment(start: string, end: string): WindowTimelineSegment {
  return {
    key: `gap-${start}-${end}`,
    kind: 'gap',
    status: 'gap',
    start,
    end,
    widthPercent: 0,
    fetchedCount: 0,
    totalResults: null,
    intensity: 0,
    windowIds: [],
    windows: [],
  };
}

function sumNullable(left: number | null, right: number | null): number | null {
  if (left == null && right == null) {
    return null;
  }
  return (left ?? 0) + (right ?? 0);
}

function maxIso(left: string, right: string): string {
  return Date.parse(left) >= Date.parse(right) ? left : right;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
