#!/usr/bin/env node
import fs from 'node:fs';
import { analyze } from './agent.js';
import { publicError } from './errors.js';

function argsOf(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--file' || argv[i] === '-f') args.filePath = argv[++i];
    else if (argv[i] === '--question' || argv[i] === '-q') args.question = argv[++i];
    else if (argv[i] === '--log') args.logPath = argv[++i];
    else if (argv[i] === '--help' || argv[i] === '-h') args.help = true;
  }
  return args;
}

const args = argsOf(process.argv.slice(2));
if (args.help) {
  console.log('Usage: node src/cli.js --file <data.csv|data.xlsx> --question <question> [--log <audit.jsonl>]');
  process.exit(0);
}
let output;
const started = performance.now();
try { output = analyze(args); }
catch (error) {
  output = {
    ...publicError(error),
    audit: { ...(error.audit || { modelCalls: 0, estimatedCostCny: 0, elapsedMs: Number((performance.now() - started).toFixed(3)) }), errorRecorded: true }
  };
  process.exitCode = 1;
}
if (args.logPath) {
  const entry = { timestamp: new Date().toISOString(), file: args.filePath || null, question: args.question || null, output };
  fs.appendFileSync(args.logPath, `${JSON.stringify(entry)}\n`, 'utf8');
}
console.log(JSON.stringify(output, null, 2));
