import { AgentError } from '../errors.js';
import { parseDate } from '../profile.js';
import { aggregate, numericValues, rounded } from './shared.js';

export function trend(table, profile, { dateField, metric, operation }) {
  const dateColumn = profile.columns.find(column => column.name === dateField);
  if (dateColumn?.type === 'mixed_date') {
    throw new AgentError('dirty_date_data', `字段“${dateField}”混有无法解析的日期，请统一日期格式后再分析。`, { invalidCount: dateColumn.invalidDate });
  }
  const dated = new Map();
  let invalidDateCount = 0;
  for (const item of numericValues(table, profile, metric)) {
    const date = parseDate(item.row[dateField]);
    if (!date) { invalidDateCount++; continue; }
    if (!dated.has(date)) dated.set(date, []);
    dated.get(date).push(item.value);
  }
  if (!dated.size) throw new AgentError('invalid_date_data', `字段“${dateField}”没有可解析的日期。`);
  return {
    dateField, metric, operation, invalidDateCount,
    points: [...dated].sort(([a], [b]) => a.localeCompare(b)).map(([date, values]) => ({ date, value: rounded(aggregate(values, operation)), validCount: values.length }))
  };
}
