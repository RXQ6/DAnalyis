# Desktop M2

Electron and TypeScript host for the existing Python data analysis Agent. M2
starts a Python JSONL supervisor, streams Runtime events, and supports run
cancellation without moving business logic into Electron.

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
is available on PATH. M6 will package a dedicated Python sidecar.
