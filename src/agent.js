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
  const audit = () => ({ modelCalls: 0, estimatedCostCny: 0, rounds: 1, maxRounds: 3, toolCalls: calls, elapsedMs: roundedMs(started) });
  const execute = (tool, fn, details = {}) => {
    const call = { tool, status: 'started', ...details };
    calls.push(call);
    try {
      const value = fn();
      call.status = 'ok';
      return value;
    } catch (error) {
      call.status = 'error';
      error.audit = audit();
      throw error;
    }
  };
  const input = execute('validate_input', () => validateInput(filePath, question));
  const table = execute('load_table', () => loadTable(filePath, input.extension));
  calls.at(-1).rows = table.rows.length;
  const profile = execute('profile_table', () => profileTable(table));
  const selection = execute('route_question', () => selectTool(input.question, profile));
  if (selection.status === 'needs_input') {
    return {
      status: 'needs_input', message: selection.message,
      data: { file: path.basename(filePath), profile },
      audit: audit()
    };
  }
  calls.at(-1).selectedTool = selection.tool;
  calls.at(-1).args = selection.args;
  const result = execute(selection.tool, () => TOOLS[selection.tool](table, profile, selection.args), { args: selection.args });
  return {
    status: 'ok', analysis: selection.tool, conclusion: explain(selection.tool, result), result,
    data: { file: path.basename(filePath), rowCount: profile.rowCount, columns: profile.columns },
    audit: audit()
  };
}

function roundedMs(started) { return Number((performance.now() - started).toFixed(3)); }
