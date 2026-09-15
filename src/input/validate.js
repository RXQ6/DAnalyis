import fs from 'node:fs';
import path from 'node:path';
import { AgentError } from '../errors.js';

export const MAX_FILE_BYTES = 20 * 1024 * 1024;

export function validateInput(filePath, question) {
  if (!filePath) throw new AgentError('missing_file', '请提供一个 CSV 或 XLSX 文件。');
  if (!question || !question.trim()) {
    throw new AgentError('insufficient_question', '请补充具体分析问题，例如要分析的字段和统计方式。');
  }
  const extension = path.extname(filePath).toLowerCase();
  if (!['.csv', '.xlsx'].includes(extension)) {
    throw new AgentError('unsupported_format', '仅支持 CSV 和 XLSX 文件。', { extension: extension || null });
  }
  let stat;
  try { stat = fs.statSync(filePath); }
  catch { throw new AgentError('file_not_found', `找不到文件：${filePath}`); }
  if (!stat.isFile()) throw new AgentError('invalid_file', '输入路径不是文件。');
  if (stat.size === 0) throw new AgentError('empty_file', '文件为空，无法分析。');
  if (stat.size > MAX_FILE_BYTES) {
    throw new AgentError('file_too_large', '文件超过 20MB 限制。', { sizeBytes: stat.size, maxBytes: MAX_FILE_BYTES });
  }
  return { extension, sizeBytes: stat.size, question: question.trim() };
}
