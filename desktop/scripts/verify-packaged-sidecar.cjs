const assert = require("node:assert/strict");
const { existsSync, mkdtempSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join, resolve } = require("node:path");
const { RuntimeProcessManager } = require("../dist/src/bridge/processManager.js");
const { RuntimeClient } = require("../dist/src/bridge/runtimeClient.js");

async function main() {
  const desktopRoot = resolve(__dirname, "..");
  const projectRoot = resolve(desktopRoot, "..");
  const resources = join(desktopRoot, "release", "win-unpacked", "resources");
  const python = join(resources, "python-runtime", "python.exe");
  const bridge = join(resources, "desktop", "python", "runtime_bridge.py");
  const node = join(resources, "bin", "node.exe");
  for (const file of [python, bridge, node, join(resources, "src", "multifile_bridge.js")]) {
    assert.ok(existsSync(file), `Missing packaged resource: ${file}`);
  }
  const data = mkdtempSync(join(tmpdir(), "data-agent-packaged-sidecar-"));
  const manager = new RuntimeProcessManager({
    repoRoot: resources,
    bridgeScriptPath: bridge,
    workingDirectory: resources,
    pythonExecutable: python,
    environment: {
      DATA_AGENT_RUNTIME_DIR: join(data, "runtime"),
      PYTHONHOME: join(resources, "python-runtime"),
      PYTHONPATH: resources,
      PYTHONNOUSERSITE: "1",
      PATH: `${join(resources, "bin")};${process.env.PATH || ""}`,
    },
  });
  const runtime = new RuntimeClient(manager);
  let stdout = "";
  let stderr = "";
  manager.on("stdout", (chunk) => { stdout += chunk.toString("utf8"); });
  manager.on("stderr", (chunk) => { stderr += chunk; });
  try {
    const selected = await runtime.registerDataset(join(projectRoot, "tests", "fixtures", "sales.csv"));
    const datasetId = selected.dataset.datasetId;
    assert.match(datasetId, /^ds_/);
    const completed = new Promise((resolveEvent, rejectEvent) => {
      const timer = setTimeout(() => rejectEvent(new Error("Packaged analysis run timed out")), 30000);
      runtime.onEvent((event) => {
        if (event.type === "run_completed" || event.type === "run_failed") {
          clearTimeout(timer);
          resolveEvent(event);
        }
      });
    });
    const started = await runtime.startRun("各地区销售额总和是多少？", selected.threadId, datasetId);
    const terminal = await completed;
    assert.equal(terminal.type, "run_completed", JSON.stringify(terminal.error));
    assert.equal(terminal.thread_id, started.threadId);
    assert.equal(terminal.trace_id, started.traceId);
    assert.ok(String(terminal.payload.response).trim());
    for (const line of stdout.trim().split(/\r?\n/)) {
      const frame = JSON.parse(line);
      assert.equal(frame.protocol_version, 1);
      assert.equal(typeof frame.type, "string");
    }
    for (const line of stderr.trim().split(/\r?\n/).filter(Boolean)) {
      assert.equal(/^[{].*"protocol_version"/.test(line), false, "Protocol JSONL leaked to stderr");
    }
    console.log(JSON.stringify({
      status: terminal.type,
      route: terminal.payload.route,
      response: terminal.payload.response,
      runId: started.runId,
      threadId: started.threadId,
      traceId: started.traceId,
      protocolFrames: stdout.trim().split(/\r?\n/).length,
      stderrLines: stderr.trim() ? stderr.trim().split(/\r?\n/).length : 0,
    }));
  } finally {
    manager.stop();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
