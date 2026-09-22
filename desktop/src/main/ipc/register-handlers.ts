import { ipcMain } from "electron";
import { RuntimeClient, RuntimeRequestError } from "../../bridge/runtimeClient";
import type { IpcError, IpcResult, RunCancelResult, RunStartResult } from "../../shared/ipc";
import { IPC_CHANNELS } from "../../shared/ipc";
import { validateRunsCancelInput } from "./runs-cancel";
import { validateRunsStartInput } from "./runs-start";

function failure(error: unknown): IpcResult<never> {
  const known = error instanceof RuntimeRequestError;
  const ipcError: IpcError = {
    code: known ? error.code : "RUNTIME_UNAVAILABLE",
    message: known ? error.message : "The Python Runtime is unavailable.",
    action: "Try again.",
  };
  return { ok: false, error: ipcError };
}

export function registerIpcHandlers(runtime: RuntimeClient): void {
  ipcMain.handle(IPC_CHANNELS.runsStart, async (_event, input: unknown): Promise<IpcResult<RunStartResult>> => {
    try {
      const validation = validateRunsStartInput(input);
      if (!validation.ok) {
        return { ok: false, error: { code: "INVALID_RUN_INPUT", message: validation.message, action: "Check the message and try again." } };
      }
      const data = await runtime.startRun(validation.value.message, validation.value.threadId);
      return { ok: true, data };
    } catch (error) {
      return failure(error);
    }
  });

  ipcMain.handle(IPC_CHANNELS.runsCancel, async (_event, input: unknown): Promise<IpcResult<RunCancelResult>> => {
    try {
      const validation = validateRunsCancelInput(input);
      if (!validation.ok) {
        return { ok: false, error: { code: "INVALID_CANCEL_INPUT", message: validation.message, action: "Check the run id and try again." } };
      }
      return { ok: true, data: await runtime.cancelRun(validation.value.runId) };
    } catch (error) {
      return failure(error);
    }
  });
}
