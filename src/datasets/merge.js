import crypto from 'node:crypto';
import fs from 'node:fs';
import { AgentError } from '../errors.js';
import { loadDataset, datasetSummary } from './summary.js';

const MAX_MERGED_ROWS = 100000;

function column(profile, name, side) {
  const found = profile.columns.find(item => item.name === name);
  if (!found) throw new AgentError('missing_join_field', `${side}关联字段“${name}”不存在。`);
  return found;
}

function compatibleKeyTypes(left, right) {
  const unsafe = new Set(['mixed', 'mixed_date']);
  return left.type === right.type && !unsafe.has(left.type);
}

function keyCounts(table, key) {
  const counts = new Map();
  let emptyKeyCount = 0;
  for (const row of table.rows) {
    const value = row[key];
    if (value === '') { emptyKeyCount++; continue; }
    counts.set(value, (counts.get(value) || 0) + 1);
  }
  const duplicates = [...counts.values()].filter(count => count > 1);
  return {
    counts,
    emptyKeyCount,
    distinctKeyCount: counts.size,
    duplicateKeyCount: duplicates.length,
    duplicateRowCount: duplicates.reduce((sum, count) => sum + count - 1, 0)
  };
}

function cardinality(left, right) {
  const leftMany = left.duplicateKeyCount > 0;
  const rightMany = right.duplicateKeyCount > 0;
  if (leftMany && rightMany) return 'many_to_many';
  if (leftMany) return 'many_to_one';
  if (rightMany) return 'one_to_many';
  return 'one_to_one';
}

function outputRowCount(leftTable, rightTable, leftKey, rightKey, joinType) {
  const right = keyCounts(rightTable, rightKey).counts;
  let count = 0;
  for (const row of leftTable.rows) {
    const key = row[leftKey];
    const matches = key === '' ? 0 : (right.get(key) || 0);
    count += matches || (joinType === 'left' ? 1 : 0);
  }
  return count;
}

function outputHeaders(leftTable, rightTable, leftKey, rightKey) {
  const headers = [...leftTable.headers];
  const rightFields = [];
  for (const name of rightTable.headers) {
    if (name === rightKey && leftKey === rightKey) continue;
    let outputName = name;
    if (headers.includes(outputName)) outputName = `${name}_right`;
    if (headers.includes(outputName) || rightFields.some(item => item.outputName === outputName)) {
      throw new AgentError('join_column_collision', `合并后的字段名“${outputName}”冲突。`);
    }
    rightFields.push({ sourceName: name, outputName });
    headers.push(outputName);
  }
  return { headers, rightFields };
}

export function inspectMerge({ leftPath, rightPath, leftKey, rightKey, joinType }) {
  if (!['inner', 'left'].includes(joinType)) {
    throw new AgentError('unsupported_join_type', '第一版仅支持 inner 和 left join。');
  }
  const left = loadDataset(leftPath), right = loadDataset(rightPath);
  const leftColumn = column(left.profile, leftKey, '左侧');
  const rightColumn = column(right.profile, rightKey, '右侧');
  const typesCompatible = compatibleKeyTypes(leftColumn, rightColumn);
  const leftKeys = keyCounts(left.table, leftKey), rightKeys = keyCounts(right.table, rightKey);
  const relation = cardinality(leftKeys, rightKeys);
  const estimatedRows = outputRowCount(left.table, right.table, leftKey, rightKey, joinType);
  outputHeaders(left.table, right.table, leftKey, rightKey);
  const risks = [];
  if (!typesCompatible) risks.push('incompatible_key_types');
  if (leftKeys.emptyKeyCount || rightKeys.emptyKeyCount) risks.push('empty_join_keys');
  if (relation !== 'one_to_one') risks.push(`cardinality_${relation}`);
  if (estimatedRows > MAX_MERGED_ROWS) risks.push('output_row_limit');
  const leftSummary = datasetSummary(leftPath), rightSummary = datasetSummary(rightPath);
  const plan = {
    leftKey, rightKey, joinType,
    leftFingerprint: leftSummary.fingerprint,
    rightFingerprint: rightSummary.fingerprint,
    leftType: leftColumn.type,
    rightType: rightColumn.type,
    typesCompatible,
    leftKeyStats: {
      emptyKeyCount: leftKeys.emptyKeyCount,
      distinctKeyCount: leftKeys.distinctKeyCount,
      duplicateKeyCount: leftKeys.duplicateKeyCount,
      duplicateRowCount: leftKeys.duplicateRowCount
    },
    rightKeyStats: {
      emptyKeyCount: rightKeys.emptyKeyCount,
      distinctKeyCount: rightKeys.distinctKeyCount,
      duplicateKeyCount: rightKeys.duplicateKeyCount,
      duplicateRowCount: rightKeys.duplicateRowCount
    },
    cardinality: relation,
    estimatedRows,
    maximumRows: MAX_MERGED_ROWS,
    risks,
    safeToExecute: risks.length === 0
  };
  plan.planFingerprint = crypto.createHash('sha256').update(JSON.stringify(plan)).digest('hex');
  return plan;
}

export function executeMerge({ leftPath, rightPath, leftKey, rightKey, joinType, expectedPlanFingerprint, outputPath }) {
  const plan = inspectMerge({ leftPath, rightPath, leftKey, rightKey, joinType });
  if (plan.planFingerprint !== expectedPlanFingerprint) {
    throw new AgentError('stale_merge_plan', '数据文件或合并计划已变化，请重新检查。');
  }
  if (!plan.safeToExecute) {
    throw new AgentError('unsafe_merge_plan', '合并计划存在字段、类型或 join 基数风险。', { risks: plan.risks, cardinality: plan.cardinality });
  }
  const left = loadDataset(leftPath), right = loadDataset(rightPath);
  const { headers, rightFields } = outputHeaders(left.table, right.table, leftKey, rightKey);
  const rightRows = new Map(right.table.rows.filter(row => row[rightKey] !== '').map(row => [row[rightKey], row]));
  const rows = [];
  for (const leftRow of left.table.rows) {
    const matched = leftRow[leftKey] === '' ? null : rightRows.get(leftRow[leftKey]);
    if (!matched && joinType === 'inner') continue;
    const output = headers.map(name => leftRow[name] ?? '');
    for (const field of rightFields) output[headers.indexOf(field.outputName)] = matched?.[field.sourceName] ?? '';
    rows.push(output);
  }
  const csv = [headers, ...rows].map(row => row.map(csvValue).join(',')).join('\n') + '\n';
  fs.writeFileSync(outputPath, csv, 'utf8');
  return { rowCount: rows.length, plan };
}

function csvValue(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
