const { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } = require("node:fs");
const { basename, dirname, join, relative, resolve, sep } = require("node:path");
const { spawnSync } = require("node:child_process");

if (process.platform !== "win32") {
  throw new Error("The M6.2 Python sidecar currently supports Windows only");
}

const desktopRoot = resolve(__dirname, "..");
const projectRoot = resolve(desktopRoot, "..");
const stageRoot = resolve(desktopRoot, ".sidecar-stage");
if (stageRoot !== join(desktopRoot, ".sidecar-stage") || !stageRoot.startsWith(desktopRoot + sep)) {
  throw new Error("Unsafe sidecar staging directory");
}

const sourcePython = process.env.DATA_AGENT_PYTHON || "python";
const probe = spawnSync(sourcePython, ["-c", "import sys; print(sys.base_prefix)"], {
  encoding: "utf8",
  windowsHide: true,
});
if (probe.error || probe.status !== 0) {
  throw new Error("Set DATA_AGENT_PYTHON to a working Windows Python 3.12 with cryptography installed before packaging");
}
const pythonHome = resolve(probe.stdout.trim());
const sitePackages = join(pythonHome, "Lib", "site-packages");
for (const required of ["python.exe", "python312.dll", "Lib", "DLLs", "LICENSE.txt"]) {
  if (!existsSync(join(pythonHome, required))) throw new Error(`Python source is missing ${required}`);
}
if (!existsSync(join(sitePackages, "cryptography"))) {
  throw new Error("The packaging Python must have cryptography installed");
}

rmSync(stageRoot, { recursive: true, force: true });
const embeddedPython = join(stageRoot, "python-runtime");
mkdirSync(embeddedPython, { recursive: true });
for (const entry of readdirSync(pythonHome)) {
  const source = join(pythonHome, entry);
  if (statSync(source).isFile() && (entry.endsWith(".dll") || entry === "python.exe" || entry === "LICENSE.txt")) {
    cpSync(source, join(embeddedPython, entry));
  }
}
cpSync(join(pythonHome, "DLLs"), join(embeddedPython, "DLLs"), {
  recursive: true,
  filter: (source) => basename(source) !== "__pycache__" && !source.endsWith(".pyc"),
});
const sourceLib = join(pythonHome, "Lib");
cpSync(sourceLib, join(embeddedPython, "Lib"), {
  recursive: true,
  filter: (source) => {
    const part = relative(sourceLib, source);
    return part !== "site-packages" && basename(source) !== "__pycache__" && !source.endsWith(".pyc");
  },
});
const stagedSite = join(embeddedPython, "Lib", "site-packages");
mkdirSync(stagedSite, { recursive: true });
for (const entry of readdirSync(sitePackages)) {
  if (/^(cryptography|cffi|pycparser)(-|$)/.test(entry) || entry === "_cffi_backend.cp312-win_amd64.pyd") {
    cpSync(join(sitePackages, entry), join(stagedSite, entry), {
      recursive: true,
      filter: (source) => basename(source) !== "__pycache__" && !source.endsWith(".pyc"),
    });
  }
}

for (const name of [
  "agent", "charts", "context_compression", "datasets", "guardrails", "hitl",
  "mcp_adapter", "memory", "observability", "session", "skill_runtime",
  "subagents", "tools", "workflow",
]) {
  cpSync(join(projectRoot, name), join(stageRoot, name), {
    recursive: true,
    filter: (source) => basename(source) !== "__pycache__" && !source.endsWith(".pyc"),
  });
}
cpSync(join(desktopRoot, "python", "runtime_bridge.py"), join(stageRoot, "desktop", "python", "runtime_bridge.py"), {
  recursive: true,
});
cpSync(join(projectRoot, "src"), join(stageRoot, "src"), {
  recursive: true,
  filter: (source) => statSync(source).isDirectory() || source.endsWith(".js"),
});
const nodeBinary = process.env.DATA_AGENT_NODE || process.execPath;
if (!existsSync(nodeBinary)) throw new Error("Node executable for the data bridge was not found");
cpSync(nodeBinary, join(stageRoot, "bin", "node.exe"));
const nodeLicense = join(dirname(nodeBinary), "LICENSE");
if (existsSync(nodeLicense)) cpSync(nodeLicense, join(stageRoot, "bin", "NODE_LICENSE.txt"));

console.log(`Staged private Python ${probe.stdout.trim()} and Node bridge in ${stageRoot}`);
