import fs from 'node:fs';
import { AgentError } from '../errors.js';
import { parseCsv } from './csv.js';
import { parseXlsx } from './xlsx.js';

export function loadTable(filePath, extension) {
  let matrix;
  const buffer = fs.readFileSync(filePath);
  try { matrix = extension === '.csv' ? parseCsv(buffer) : parseXlsx(buffer); }
  catch (error) { if (error instanceof AgentError) throw error; throw new AgentError('unreadable_file', '文件无法可靠读取。'); }
  const headers = matrix[0].map(value => String(value).trim());
  if (!headers.length || headers.every(value => !value)) throw new AgentError('missing_header', '文件缺少表头。');
  const duplicates = headers.filter((value, index) => value && headers.indexOf(value) !== index);
  if (headers.some(value => !value) || duplicates.length) {
    throw new AgentError('invalid_header', '表头包含空字段或重复字段，无法可靠分析。', { duplicates: [...new Set(duplicates)] });
  }
  const malformedRows = matrix.slice(1).map((row, index) => ({ rowNumber: index + 2, width: row.length }))
    .filter(item => item.width !== headers.length);
  if (malformedRows.length) {
    throw new AgentError('inconsistent_columns', '部分数据行的列数与表头不一致。', { rows: malformedRows.slice(0, 20) });
  }
  const rows = matrix.slice(1).filter(row => row.some(value => String(value).trim() !== '')).map(row =>
    Object.fromEntries(headers.map((header, index) => [header, String(row[index] ?? '').trim()])));
  if (!rows.length) throw new AgentError('empty_data', '文件没有可分析的数据行。');
  return { headers, rows };
}
