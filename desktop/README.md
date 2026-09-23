# Desktop M6.5

Electron and TypeScript host for the existing Python data analysis Agent. In
development it starts a Python JSONL supervisor, streams Runtime events, and
supports run cancellation without moving business logic into Electron.

## Development

```powershell
cd desktop
npm install
$env:DATA_AGENT_PYTHON = "C:\\path\\to\\python.exe"
npm run dev
```

Enter a message and select **Send**. Electron Main validates the IPC payload,
starts a real Python Runtime run, and projects ordered JSONL events into the
event list. **Stop** sends `run.cancel` to the Python supervisor.

## Tests

```powershell
cd desktop
$env:DATA_AGENT_PYTHON = "C:\\path\\to\\python.exe"
npm test
```

`DATA_AGENT_PYTHON` is optional when a project `.venv` or `python`/`python3`
is available on PATH.

## Windows packaging

Set `DATA_AGENT_PYTHON` to a Windows Python 3.12 executable with `cryptography`
installed on the build machine. From `desktop`, run `npm.cmd run pack:win` for both `release/win-unpacked` and the
NSIS installer in `release`. Run `npm run pack:win:dir` for unpacked output only.
The build uses the Electron distribution already installed in `node_modules`;
it does not depend on an absolute development-machine path. Main, Preload and
Renderer are in `resources/app.asar`. Main uses checkout-relative paths in dev
and `process.resourcesPath` in packaged mode. Runtime data is placed under
Electron's standard `app.getPath("userData")/runtime` directory. `build:sidecar`
stages a private Python interpreter, standard library, required third-party
modules, unchanged project Python modules, the JSONL Bridge, existing data-bridge
JavaScript and a private Node executable. electron-builder copies these into
`resources` outside `app.asar`; packaged Main launches `resources/python-runtime/python.exe`
with `resources/desktop/python/runtime_bridge.py`. Worker processes use the
same private Python, and the data bridge uses `resources/bin/node.exe`.

Run `npm.cmd run verify:packaged-sidecar` after packaging to verify CSV registration,
a real analysis run, and protocol-only stdout. The packaged Electron startup
smoke is enabled with `DATA_AGENT_PACKAGING_SMOKE=1` and verifies a real run
through Preload/Main/Python. Missing Python or Bridge files return structured
IPC errors while Electron remains alive. The installer is currently unsigned,
uses Electron's default icon, and has not been independently installed on a
clean machine.

## Electron E2E

With `DATA_AGENT_PYTHON` set, run `npm.cmd run test:e2e` for the development
Electron window. After `npm.cmd run pack:win`, run
`npm.cmd run test:e2e:packaged` to load packaged Renderer/Preload and private
Python/Node resources in a real Electron window. Both modes click the actual UI
and use the production IPC handlers and Python Bridge. Only the operating-system
file dialog response is supplied with deterministic CSV/XLSX test paths; core
IPC and Runtime events are not mocked. Each failed stage reports its name,
error and current UI state. `npm.cmd test` also includes the development E2E.

## Packaged smoke

After `npm.cmd run pack:win`, run `npm.cmd run test:smoke:packaged` from `desktop`.
This launches `release/win-unpacked/Data Analysis Agent.exe` twice as two
independent packaged processes. The first process selects a deterministic CSV
through the actual Renderer → Preload → Main → Python path, sends a real
analysis run, and checks Runtime events and completion. The second process uses
the same standard Electron userData directory and confirms Session List/Resume
restores the previous messages and Trace without starting another run. Results
are written to `release/m6.4-smoke-*/first.json` and `resume.json`. Only the
native file chooser result is supplied by the test; the chooser's manual UI,
NSIS installation and clean-machine deployment are not covered by this smoke.

## Release gate

The M6.5 release gate and artifact hashes are recorded in
`../docs/Desktop-M6.5-Release-Report.md`. The current NSIS installer was
actually installed into an isolated directory on the build machine; the
installed executable passed the same two-process CSV analysis and Session
recovery smoke. For an installed executable, pass its absolute path with
`node scripts/verify-packaged-smoke.cjs --executable <path> --label installed-smoke`.
This does not replace clean-machine, native file-dialog, upgrade/uninstall, or
trusted-signature verification.
