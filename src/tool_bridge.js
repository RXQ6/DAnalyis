#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { validateInput } from './input/validate.js';
import { loadTable } from './input/load.js';
import { profileTable } from './profile.js';
import { statistics, topN } from './tools/statistics.js';
import { groupCompare } from './tools/group.js';
import { trend } from './tools/trend.js';
import { anomaly } from './tools/anomaly.js';
import { AgentError, publicError } from './errors.js';

function filteredTable(table, filters = {}) {
  for (const field of Object.keys(filters)) {
    if (!table.headers.includes(field)) throw new AgentError('missing_field', `字段“${field}”不存在。`);
  }
  const rows = table.rows.filter(row => Object.entries(filters).every(([field, value]) => row[field] === String(value)));
  if (!rows.length) throw new AgentError('empty_selection', '筛选条件没有匹配到数据。');
  return { headers: table.headers, rows };
}

function inspectData(table, profile) {
  return { headers: table.headers, profile };
}

const HANDLERS = {
  inspect_data: (table, profile) => inspectData(table, profile),
  basic_stats: (table, profile, args) => statistics(table, profile, args),
  group_compare: (table, profile, args) => groupCompare(table, profile, args),
  trend_analysis: (table, profile, args) => {
    const selected = filteredTable(table, args.filters || {});
    return trend(selected, profileTable(selected), args);
  },
  detect_anomaly: (table, profile, args) => anomaly(table, profile, args),
  top_n: (table, profile, args) => topN(table, profile, args)
};

let output;
try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  const handler = HANDLERS[request.tool];
  if (!handler) throw new AgentError('unknown_tool', `工具“${request.tool}”未注册。`);
  const input = validateInput(request.dataset, 'registered tool execution');
  const table = loadTable(request.dataset, input.extension || path.extname(request.dataset).toLowerCase());
  const profile = profileTable(table);
  output = { status: 'ok', result: handler(table, profile, request.arguments || {}) };
} catch (error) {
  output = publicError(error);
  process.exitCode = 1;
}
console.log(JSON.stringify(output));

