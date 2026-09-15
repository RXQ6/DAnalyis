import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { analyze } from '../src/agent.js';
import { AgentError } from '../src/errors.js';
import { createSimpleXlsx } from './helpers/xlsx-fixture.js';

function fixture(name, content) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'data-agent-'));
  const filePath = path.join(directory, name);
  fs.writeFileSync(filePath, content);
  return filePath;
}

test('computes CSV sum and handles quoted fields', () => {
  const filePath = fixture('sales.csv', '商品,销售额\n"A, 特价",10\nB,20\n');
  const output = analyze({ filePath, question: '计算销售额总和' });
  assert.equal(output.status, 'ok');
  assert.equal(output.analysis, 'statistics');
  assert.equal(output.result.value, 30);
  assert.equal(output.audit.modelCalls, 0);
  assert.match(output.conclusion, /30/);
});

test('counts non-empty values in a text column', () => {
  const filePath = fixture('items.csv', '商品\nA\nB\n');
  const output = analyze({ filePath, question: '统计商品数量' });
  assert.equal(output.result.value, 2);
});

test('computes XLSX average', () => {
  const filePath = fixture('sales.xlsx', createSimpleXlsx([['商品', '销售额'], ['A', 10], ['B', 20]]));
  const output = analyze({ filePath, question: '计算销售额平均值' });
  assert.equal(output.result.value, 15);
});

test('groups a numeric metric by the requested category', () => {
  const filePath = fixture('sales.csv', '地区,销售额\n北区,10\n南区,7\n北区,20\n');
  const output = analyze({ filePath, question: '按地区分组统计销售额总和' });
  assert.deepEqual(output.result.groups.map(item => [item.group, item.value]), [['北区', 30], ['南区', 7]]);
});

test('returns chronological trend points and selects the trend tool', () => {
  const filePath = fixture('sales.csv', '日期,销售额\n2026-01-02,20\n2026-01-01,5\n2026-01-01,10\n');
  const output = analyze({ filePath, question: '分析销售额随日期的趋势' });
  assert.equal(output.analysis, 'trend');
  assert.deepEqual(output.result.points.map(item => [item.date, item.value]), [['2026-01-01', 15], ['2026-01-02', 20]]);
});

test('detects IQR anomalies', () => {
  const filePath = fixture('values.csv', '数值\n10\n10\n11\n10\n100\n');
  const output = analyze({ filePath, question: '识别数值异常值' });
  assert.equal(output.analysis, 'anomaly');
  assert.deepEqual(output.result.anomalies, [{ rowNumber: 6, value: 100 }]);
});

test('rejects dirty numeric fields instead of coercing them', () => {
  const filePath = fixture('dirty.csv', '销售额\n10\n错误\n20\n');
  assert.throws(() => analyze({ filePath, question: '计算销售额总和' }), error =>
    error instanceof AgentError && error.code === 'dirty_numeric_data');
});

test('reports a missing requested field', () => {
  const filePath = fixture('sales.csv', '销售额\n10\n');
  assert.throws(() => analyze({ filePath, question: '计算利润总和' }), error =>
    error instanceof AgentError && error.code === 'missing_field');
});

test('asks for clarification on a vague question', () => {
  const filePath = fixture('sales.csv', '销售额\n10\n');
  const output = analyze({ filePath, question: '看看这个数据' });
  assert.equal(output.status, 'needs_input');
});

test('rejects unsupported formats', () => {
  const filePath = fixture('sales.txt', '销售额\n10\n');
  assert.throws(() => analyze({ filePath, question: '计算销售额总和' }), error =>
    error instanceof AgentError && error.code === 'unsupported_format');
});

test('rejects inconsistent CSV rows', () => {
  const filePath = fixture('broken.csv', '商品,销售额\nA,10,extra\n');
  assert.throws(() => analyze({ filePath, question: '计算销售额总和' }), error =>
    error instanceof AgentError && error.code === 'inconsistent_columns');
});

test('rejects mixed date formats before trend calculation', () => {
  const filePath = fixture('dates.csv', '日期,销售额\n2026-01-01,10\n01/02/2026,20\n');
  assert.throws(() => analyze({ filePath, question: '分析销售额随日期的趋势' }), error =>
    error instanceof AgentError && error.code === 'dirty_date_data' && error.audit.toolCalls.at(-1).status === 'error');
});

test('does not rank a text field when the requested metric is absent', () => {
  const filePath = fixture('customers.csv', '客户,收入\n甲,10\n乙,20\n');
  assert.throws(() => analyze({ filePath, question: '找出客户满意度最高的客户' }), error =>
    error instanceof AgentError && error.code === 'missing_field');
});
