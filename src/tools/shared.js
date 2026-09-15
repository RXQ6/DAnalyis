import { AgentError } from '../errors.js';
import { parseNumber } from '../profile.js';

export function numericValues(table, profile, field) {
  const column = profile.columns.find(item => item.name === field);
  if (!column) throw new AgentError('missing_field', `字段“${field}”不存在。`);
  if (column.type === 'mixed') {
    throw new AgentError('dirty_numeric_data', `字段“${field}”混有非数值文本，请清洗或修正后再分析。`, { invalidCount: column.invalidNumeric });
  }
  if (column.type !== 'number') throw new AgentError('invalid_field_type', `字段“${field}”不是数值字段。`, { actualType: column.type });
  return table.rows.map((row, rowIndex) => ({ row, rowNumber: rowIndex + 2, value: parseNumber(row[field]) }))
    .filter(item => item.value !== null);
}

export function aggregate(values, operation) {
  if (!values.length) throw new AgentError('no_numeric_data', '没有可用于计算的数值。');
  if (operation === 'count') return values.length;
  if (operation === 'sum') return values.reduce((sum, value) => sum + value, 0);
  if (operation === 'average') return values.reduce((sum, value) => sum + value, 0) / values.length;
  if (operation === 'minimum') return Math.min(...values);
  if (operation === 'maximum') return Math.max(...values);
  throw new AgentError('unsupported_operation', `不支持的统计方式：${operation}`);
}

export function rounded(value) {
  return Number.isInteger(value) ? value : Number(value.toPrecision(12));
}
