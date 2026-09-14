import { aggregate, numericValues, rounded } from './shared.js';

export function groupCompare(table, profile, { groupBy, metric, operation }) {
  const groups = new Map();
  for (const item of numericValues(table, profile, metric)) {
    const key = item.row[groupBy] || '(空)';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item.value);
  }
  return {
    groupBy, metric, operation,
    groups: [...groups].map(([group, values]) => ({ group, value: rounded(aggregate(values, operation)), validCount: values.length }))
      .sort((a, b) => b.value - a.value || a.group.localeCompare(b.group))
  };
}
