import { AgentError } from '../errors.js';
import { numericValues, rounded } from './shared.js';

function quantile(sorted, q) {
  const index = (sorted.length - 1) * q;
  const lower = Math.floor(index), fraction = index - lower;
  return sorted[lower] + (sorted[Math.min(lower + 1, sorted.length - 1)] - sorted[lower]) * fraction;
}

export function anomaly(table, profile, { metric }) {
  const items = numericValues(table, profile, metric);
  if (items.length < 4) throw new AgentError('insufficient_data', '异常识别至少需要 4 个有效数值。', { validCount: items.length });
  const sorted = items.map(item => item.value).sort((a, b) => a - b);
  const q1 = quantile(sorted, 0.25), q3 = quantile(sorted, 0.75), iqr = q3 - q1;
  const lowerBound = q1 - 1.5 * iqr, upperBound = q3 + 1.5 * iqr;
  const anomalies = items.filter(item => item.value < lowerBound || item.value > upperBound)
    .map(item => ({ rowNumber: item.rowNumber, value: rounded(item.value) }));
  return {
    metric, method: 'iqr_1.5', q1: rounded(q1), q3: rounded(q3),
    lowerBound: rounded(lowerBound), upperBound: rounded(upperBound), anomalyCount: anomalies.length, anomalies
  };
}
