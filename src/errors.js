export class AgentError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'AgentError';
    this.code = code;
    this.details = details;
  }
}

export function publicError(error) {
  if (error instanceof AgentError) {
    return { status: 'error', error: { code: error.code, message: error.message, ...error.details } };
  }
  return {
    status: 'error',
    error: { code: 'internal_error', message: '分析失败：发生未预期的内部错误。' }
  };
}
