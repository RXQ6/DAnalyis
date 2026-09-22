import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { join } from "node:path";

export interface RuntimeProcessOptions {
  repoRoot: string;
  pythonExecutable?: string;
  environment?: NodeJS.ProcessEnv;
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
    this.starting = new Promise<void>((resolve, reject) => {
      const child = spawn(
        this.pythonExecutable(),
        [join(this.options.repoRoot, "desktop", "python", "runtime_bridge.py")],
        {
          cwd: this.options.repoRoot,
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
        reject(error);
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
