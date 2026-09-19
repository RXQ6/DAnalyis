#!/usr/bin/env node
import fs from 'node:fs';
import { publicError, AgentError } from './errors.js';
import { datasetSummary } from './datasets/summary.js';
import { executeMerge, inspectMerge } from './datasets/merge.js';

let output;
try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (request.action === 'summarize') {
    output = { status: 'ok', result: datasetSummary(request.dataset) };
  } else if (request.action === 'inspect_merge') {
    output = { status: 'ok', result: inspectMerge(request) };
  } else if (request.action === 'merge') {
    output = { status: 'ok', result: executeMerge(request) };
  } else {
    throw new AgentError('unsupported_multifile_action', `不支持的多文件操作：${request.action}`);
  }
} catch (error) {
  output = publicError(error);
  process.exitCode = 1;
}
console.log(JSON.stringify(output));
