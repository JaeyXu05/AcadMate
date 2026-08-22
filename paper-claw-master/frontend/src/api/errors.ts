export interface ApiProblem {
  status: number;
  message: string;
  detail?: unknown;
}

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(problem: ApiProblem) {
    super(problem.message);
    this.name = 'ApiError';
    this.status = problem.status;
    this.detail = problem.detail;
  }
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Unexpected error';
}

export async function toApiError(response: Response): Promise<ApiError> {
  const fallback = response.statusText || `Request failed with ${response.status}`;
  try {
    const payload = await response.json();
    if (typeof payload?.message === 'string') {
      return new ApiError({ status: response.status, message: payload.message, detail: payload.detail });
    }
    if (typeof payload?.detail === 'string') {
      return new ApiError({ status: response.status, message: payload.detail, detail: payload.detail });
    }
    if (Array.isArray(payload?.detail)) {
      return new ApiError({ status: response.status, message: 'Validation failed', detail: payload.detail });
    }
    return new ApiError({ status: response.status, message: fallback, detail: payload });
  } catch {
    return new ApiError({ status: response.status, message: fallback });
  }
}
