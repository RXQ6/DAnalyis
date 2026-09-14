import path from 'node:path';
import { validateInput } from './input/validate.js';
import { loadTable } from './input/load.js';
import { profileTable } from './profile.js';
import { selectTool } from './router.js';
import { statistics, topN } from './tools/statistics.js';
import { groupCompare } from './tools/group.js';
import { trend } from './tools/trend.js';
import { anomaly } from './tools/anomaly.js';
import { explain } from './presenter.js';

const TOOLS = { statistics, top_n: topN, group_compare: groupCompare, trend, anomaly };

export function analyze({ filePath, question }) {
  const started = performance.now();
  const calls = [];
  const input = validateInput(filePath, question);
  calls.push({ tool: 'validate_input', status: 'ok' });
  const table = loadTable(filePath, input.extension);
  calls.push({ tool: 'load_table', status: 'ok', rows: table.rows.length });
  const profile = profileTable(table);
  calls.push({ tool: 'profile_table', status: 'ok' });
  const selection = selectTool(input.question, profile);
  if (selection.status === 'needs_input') {
    return {
      status: 'needs_input', message: selection.message,
      data: { file: path.basename(filePath), profile },
      audit: { modelCalls: 0, estimatedCostCny: 0, rounds: 1, maxRounds: 3, toolCalls: calls, elapsedMs: roundedMs(started) }
    };
  }
  calls.push({ tool: selection.tool, status: 'selected' });
  const result = TOOLS[selection.tool](table, profile, selection.args);
  calls.at(-1).status = 'ok';
  return {
    status: 'ok', analysis: selection.tool, conclusion: explain(selection.tool, result), result,
    data: { file: path.basename(filePath), rowCount: profile.rowCount, columns: profile.columns },
    audit: { modelCalls: 0, estimatedCostCny: 0, rounds: 1, maxRounds: 3, toolCalls: calls, elapsedMs: roundedMs(started) }
  };
}

function roundedMs(started) { return Number((performance.now() - started).toFixed(3)); }
