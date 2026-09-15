import { aggregate, numericValues, rounded } from './shared.js';

export function statistics(table, profile, { metric, operation }) {
  if (operation === 'count') {
    const column = profile.columns.find(item => item.name === metric);
    return { metric, operation, value: column.nonEmpty, validCount: column.nonEmpty };
  }
  const items = numericValues(table, profile, metric);
  return { metric, operation, value: rounded(aggregate(items.map(item => item.value), operation)), validCount: items.length };
}

export function topN(table, profile, { metric, label, count }) {
  const safeCount = Math.max(1, Math.min(1000, count));
  const items = numericValues(table, profile, metric).sort((a, b) => b.value - a.value || a.rowNumber - b.rowNumber).slice(0, safeCount);
  return {
    metric, count: items.length,
    items: items.map(item => ({ rank: 0, label: label ? item.row[label] : `row_${item.rowNumber}`, value: rounded(item.value), rowNumber: item.rowNumber }))
      .map((item, index) => ({ ...item, rank: index + 1 }))
  };
}
