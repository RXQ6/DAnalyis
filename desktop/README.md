# Desktop（Electron）

Electron and TypeScript host for the existing Python data analysis Agent. In
development it starts a Python JSONL supervisor, streams Runtime events, and
supports run cancellation without moving business logic into Electron.

The Renderer is **not a standalone website**. Opening
`src/renderer/index.html` or `dist/src/renderer/index.html` in a browser
does not provide Electron Main, the sandboxed preload API or the Python
Runtime. Start the Electron app with the command below or launch a packaged
exe. No separate browser or web server is required.

Current desktop screenshots and the Phase 1.4 Windows installer link are in the
[repository README](../README.md#桌面界面预览). The installer is a GitHub Release
asset, not a file in the source branch.

## Development

From the repository root:

```powershell
cd desktop
npm.cmd ci
$env:DATA_AGENT_PYTHON = "C:\path\to\python.exe"
npm.cmd start
```

`npm.cmd start` builds Main, preload and Renderer, then starts the real
Electron window. In PowerShell, the `npm.cmd` spelling also avoids machines
whose execution policy blocks `npm.ps1`. `DATA_AGENT_PYTHON` may be omitted
if the repository `.venv` or a compatible Python on PATH is available.

Use **选择 CSV / XLSX** or **添加数据** to open the native Windows file picker. The selected
path goes through Renderer → preload → Main → Python; DatasetRegistry reads the
file. Type a question and select **发送**. The status and collapsible **分析过程**
are projected from sequence-ordered Python events; **停止** sends `run.cancel`.
Sessions come from Python SessionStore, Charts consume existing Chart Specs,
and approval decisions are validated by Python HITL. The Renderer does not
parse datasets, recalculate analytical figures or decide whether an approval
is valid.

## Tests

From the repository root:

```powershell
cd desktop
$env:DATA_AGENT_PYTHON = "C:\path\to\python.exe"
npm.cmd test
```

`DATA_AGENT_PYTHON` is optional when a project `.venv` or `python`/`python3`
is available on PATH.

## Windows packaging

Set `DATA_AGENT_PYTHON` to a Windows Python 3.12 executable with `cryptography`
installed on the build machine. From `desktop`, run `npm.cmd run pack:win` for
both `release/win-unpacked` and `release/Data Analysis Agent Setup 0.1.0.exe`.
Run `npm.cmd run pack:win:dir` for unpacked output only. These are local build
artifacts excluded by `desktop/.gitignore`; pushing source or a README does not
upload an installer to GitHub.
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
IPC errors while Electron remains alive. The installer is currently unsigned
and has not been independently installed on a clean machine. The window,
installer and in-app icon use the same replaceable brand asset entry; the
current mark is a working placeholder.

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

## Installed application check

For a new installer build, close old app processes and install into a known
directory. Launch **that directory's** `Data Analysis Agent.exe`; do not use
`win-unpacked`, dev mode or an old shortcut. Confirm the process location in
Task Manager, then:

1. Click **选择 CSV / XLSX** and manually select `../tests/fixtures/sales.csv`
   in the real Windows dialog.
2. Send “按地区汇总销售额”; expect running, **分析过程** and a final completed
   response grounded in the CSV.
3. Fully exit, reopen the installed exe, and select the previous Session.
   Its messages and events should return without repeating the old run.

The packaged smoke can verify an installed executable without using dev mode:

```powershell
node scripts/verify-packaged-smoke.cjs --executable "C:\path\to\installed\Data Analysis Agent.exe" --label installed-smoke
```

That automation supplies a deterministic file-dialog return path; **it does
not prove that a human can click through the native dialog**. It also does
not verify a clean-machine deployment, installer upgrade/uninstall behaviour
or trusted code signing. Session and approval data use Electron's standard
`app.getPath("userData")/runtime`; do not delete it for a routine smoke.

## Release gate

The M6.5 release gate and artifact hashes are recorded in
`../docs/Desktop-M6.5-Release-Report.md`. That report's NSIS installer was
actually installed into an isolated directory on the build machine; the
installed executable passed the same two-process CSV analysis and Session
recovery smoke. Its PASS does not automatically apply to a later rebuilt
installer, which needs its own installed-app check.
