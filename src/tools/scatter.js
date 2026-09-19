import { AgentError } from '../errors.js';
import { parseNumber } from '../profile.js';

function numericColumn(profile, field) {
  const column = profile.columns.find(item => item.name === field);
  if (!column) throw new AgentError('missing_field', `字段“${field}”不存在。`);
  if (column.type === 'mixed') {
    throw new AgentError('dirty_numeric_data', `字段“${field}”混有非数值文本，请清洗或修正后再分析。`, { invalidCount: column.invalidNumeric });
  }
  if (column.type !== 'number') {
    throw new AgentError('invalid_field_type', `字段“${field}”不是数值字段。`, { actualType: column.type });
  }
}

export function scatterData(table, profile, args) {
  if (args.xField === args.yField) {
    throw new AgentError('duplicate_scatter_field', '散点图需要两个不同的数值字段。');
  }
  numericColumn(profile, args.xField);
  numericColumn(profile, args.yField);
  let omittedPairCount = 0;
  const points = [];
  for (const [index, row] of table.rows.entries()) {
    const x = parseNumber(row[args.xField]);
    const y = parseNumber(row[args.yField]);
    if (x === null || y === null) {
      omittedPairCount += 1;
      continue;
    }
    points.push({ x, y, rowNumber: index + 2 });
  }
  if (!points.length) throw new AgentError('no_numeric_pairs', '没有可用于散点图的成对数值。');
  return {
    xField: args.xField,
    yField: args.yField,
    metric: args.yField,
    pointCount: points.length,
    omittedPairCount,
    points
  };
}
