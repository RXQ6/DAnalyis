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

const TOOL_CATALOG = JSON.parse(
  fs.readFileSync(new URL('../tools/catalog.json', import.meta.url), 'utf8')
);

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
  inspect_data: (table, profile, _args) => inspectData(table, profile),
  basic_stats: (table, profile, args) => statistics(table, profile, args),
  group_compare: (table, profile, args) => groupCompare(table, profile, args),
  trend_analysis: (table, profile, args) => {
    const selected = filteredTable(table, args.filters || {});
    return trend(selected, profileTable(selected), args);
  },
  detect_anomaly: (table, profile, args) => anomaly(table, profile, args),
  top_n: (table, profile, args) => topN(table, profile, args)
};

function registeredHandlers(catalog, handlers) {
  if (!catalog || !Array.isArray(catalog.tools)) throw new Error('Invalid tool catalog.');
  const names = catalog.tools.map(tool => tool?.name);
  if (names.some(name => typeof name !== 'string' || !name)) throw new Error('Tool catalog contains an invalid name.');
  if (new Set(names).size !== names.length) throw new Error('Tool catalog contains duplicate names.');
  for (const name of names) {
    const handler = handlers[name];
    if (typeof handler !== 'function') throw new Error(`Registered tool has no handler: ${name}`);
    if (handler.length !== 3) throw new Error(`Tool handler must accept (table, profile, args): ${name}`);
  }
  const unregistered = Object.keys(handlers).filter(name => !names.includes(name));
  if (unregistered.length) throw new Error(`Handlers bypass the registry: ${unregistered.join(', ')}`);
  return new Map(names.map(name => [name, handlers[name]]));
}

const REGISTERED_HANDLERS = registeredHandlers(TOOL_CATALOG, HANDLERS);

let output;
try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  const handler = REGISTERED_HANDLERS.get(request.tool);
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
