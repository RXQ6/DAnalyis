const { spawnSync } = require("node:child_process");
const { join, resolve } = require("node:path");
const electron = require("electron");

const desktopRoot = resolve(__dirname, "..");
const result = spawnSync(electron, [join(desktopRoot, "dist", "tests", "m6-electron-e2e.js")], {
  cwd: desktopRoot,
  env: { ...process.env, DATA_AGENT_E2E_PACKAGED: "1" },
  stdio: "inherit",
  windowsHide: true,
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
