import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { resolveRuntimePaths } from "../src/main/runtime-paths";
import { secureWebPreferences } from "../src/main/window-options";
import { RuntimeProcessManager, RuntimeStartupError } from "../src/bridge/processManager";

const desktopRoot = resolve(__dirname, "../..");

test("M6.1 separates development and packaged runtime paths", () => {
  const mainDirectory = join(desktopRoot, "dist", "src", "main");
  const resourcesDirectory = join("C:", "installed-app", "resources");
  const userDataDirectory = join("C:", "Users", "tester", "AppData", "Roaming", "Data Analysis Agent");
  const development = resolveRuntimePaths(false, mainDirectory, resourcesDirectory, userDataDirectory);
  const packaged = resolveRuntimePaths(true, mainDirectory, resourcesDirectory, userDataDirectory);

  assert.equal(development.repoRoot, resolve(desktopRoot, ".."));
  assert.ok(existsSync(development.bridgeScriptPath));
  assert.equal(packaged.repoRoot, resourcesDirectory);
  assert.equal(packaged.bridgeScriptPath, join(resourcesDirectory, "desktop", "python", "runtime_bridge.py"));
  assert.equal(packaged.workingDirectory, resourcesDirectory);
  assert.equal(packaged.runtimeDataDirectory, join(userDataDirectory, "runtime"));
  assert.equal(packaged.pythonExecutable, join(resourcesDirectory, "python-runtime", "python.exe"));
  assert.equal(packaged.pythonHome, join(resourcesDirectory, "python-runtime"));
  assert.equal(packaged.nodeBinDirectory, join(resourcesDirectory, "bin"));
  assert.equal(packaged.bridgeScriptPath.includes(development.repoRoot), false);
});

test("M6.2 packages Python, project modules, Node bridge and private executables", () => {
  const config = JSON.parse(readFileSync(join(desktopRoot, "package.json"), "utf8"));
  assert.equal(config.build.extraResources[0].from, ".sidecar-stage");
  assert.match(config.scripts["pack:win"], /build:sidecar/);
  const staging = readFileSync(join(desktopRoot, "scripts", "stage-python-sidecar.cjs"), "utf8");
  for (const name of ["runtime_bridge.py", "cryptography", "node.exe", "src", "python-runtime"]) {
    assert.ok(staging.includes(name), name);
  }
  assert.equal(staging.includes("C:\\Users\\29486"), false);
});

test("missing packaged Python returns a structured startup error before spawn", async () => {
  const manager = new RuntimeProcessManager({
    repoRoot: resolve(desktopRoot, ".."),
    bridgeScriptPath: join(desktopRoot, "python", "runtime_bridge.py"),
    pythonExecutable: join(desktopRoot, "missing-private-python.exe"),
  });
  await assert.rejects(manager.start(), (error: unknown) =>
    error instanceof RuntimeStartupError && error.code === "PYTHON_RUNTIME_NOT_FOUND",
  );
});

test("M6.1 packages Main, Preload, Renderer and preserves window isolation", () => {
  const config = JSON.parse(readFileSync(join(desktopRoot, "package.json"), "utf8"));
  assert.equal(config.main, "dist/src/main/index.js");
  assert.equal(config.build.asar, true);
  assert.deepEqual(config.build.files[0], "dist/src/**/*");
  for (const file of ["main/index.js", "preload/index.js", "renderer/index.html", "renderer/bundle.js"]) {
    assert.ok(existsSync(join(desktopRoot, "dist", "src", file)), file);
  }
  const preferences = secureWebPreferences("preload.js");
  assert.equal(preferences.contextIsolation, true);
  assert.equal(preferences.nodeIntegration, false);
  assert.equal(preferences.sandbox, true);
});
