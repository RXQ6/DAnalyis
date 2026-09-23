import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { join } from "node:path";

export interface RuntimeProcessOptions {
  repoRoot: string;
  bridgeScriptPath?: string;
  workingDirectory?: string;
  pythonExecutable?: string;
  environment?: NodeJS.ProcessEnv;
}

export class RuntimeStartupError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
  }
}

export class RuntimeProcessManager extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null;
  private starting: Promise<void> | null = null;
  private expectedExit = false;

  constructor(private readonly options: RuntimeProcessOptions) {
    super();
  }

  async start(): Promise<void> {
    if (this.child && this.child.exitCode === null && !this.child.killed) {
      return;
    }
    if (this.starting) {
      return this.starting;
    }
    const bridgeScript = this.options.bridgeScriptPath ?? join(this.options.repoRoot, "desktop", "python", "runtime_bridge.py");
    if (!existsSync(bridgeScript)) {
      throw new RuntimeStartupError("PYTHON_BRIDGE_NOT_FOUND", "Packaged Python Runtime bridge is missing.");
    }
    const pythonExecutable = this.pythonExecutable();
    if (this.options.pythonExecutable && !existsSync(pythonExecutable)) {
      throw new RuntimeStartupError("PYTHON_RUNTIME_NOT_FOUND", "Packaged Python executable is missing.");
    }
    this.starting = new Promise<void>((resolve, reject) => {
      const child = spawn(
        pythonExecutable,
        [bridgeScript],
        {
          cwd: this.options.workingDirectory ?? this.options.repoRoot,
          env: {
            ...process.env,
            PYTHONIOENCODING: "utf-8",
            PYTHONUTF8: "1",
            ...this.options.environment,
          },
          stdio: ["pipe", "pipe", "pipe"],
          windowsHide: true,
          shell: false,
        },
      );
      this.child = child;
      this.expectedExit = false;
      const onError = (error: Error): void => {
        this.starting = null;
        this.child = null;
        this.emit("stderr", `Python spawn failed: ${error.message}\n`);
        reject(new RuntimeStartupError("PYTHON_START_FAILED", "Python Runtime could not start."));
      };
      child.once("error", onError);
      child.once("spawn", () => {
        child.off("error", onError);
        child.stdout.on("data", (chunk: Buffer) => this.emit("stdout", chunk));
        child.stderr.on("data", (chunk: Buffer) => this.emit("stderr", chunk.toString("utf8")));
        child.on("exit", (code, signal) => {
          const expected = this.expectedExit;
          this.child = null;
          this.emit("exit", { code, signal, expected });
        });
        this.starting = null;
        resolve();
      });
    });
    return this.starting;
  }

  sendLine(line: string): void {
    if (!this.child || this.child.exitCode !== null || this.child.killed) {
      throw new Error("Python Runtime is not running");
    }
    this.child.stdin.write(`${line}\n`, "utf8");
  }

  stop(): void {
    if (this.child && this.child.exitCode === null) {
      this.expectedExit = true;
      this.child.kill();
    }
  }

  kill(): void {
    if (this.child && this.child.exitCode === null) {
      this.expectedExit = false;
      this.child.kill();
    }
  }

  isRunning(): boolean {
    return Boolean(this.child && this.child.exitCode === null && !this.child.killed);
  }

  private pythonExecutable(): string {
    if (this.options.pythonExecutable) {
      return this.options.pythonExecutable;
    }
    if (process.env.DATA_AGENT_PYTHON) {
      return process.env.DATA_AGENT_PYTHON;
    }
    const local =
      process.platform === "win32"
        ? join(this.options.repoRoot, ".venv", "Scripts", "python.exe")
        : join(this.options.repoRoot, ".venv", "bin", "python");
    if (existsSync(local)) {
      return local;
    }
    return process.platform === "win32" ? "python" : "python3";
  }
}
