import { BrowserWindow, dialog, ipcMain } from "electron";
import { RuntimeClient, RuntimeRequestError } from "../../bridge/runtimeClient";
import type { DatasetSelectionResult, DatasetSummary, IpcError, IpcResult, RunCancelResult, RunStartResult, SessionListResult, SessionSnapshot } from "../../shared/ipc";
import { IPC_CHANNELS } from "../../shared/ipc";
import { validateFilesSelectInput } from "./files-select";
import { validateRunsCancelInput } from "./runs-cancel";
import { validateRunsStartInput } from "./runs-start";
import { validateApprovalInput, validateSessionInput } from "./session-approval";

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
  ipcMain.handle(IPC_CHANNELS.sessionsList, async (): Promise<IpcResult<SessionListResult>> => {
    try {
      return { ok: true, data: { sessions: await runtime.listSessions() } };
    } catch (error) {
      return failure(error);
    }
  });

  const sessionHandler = (resume: boolean) => async (_event: Electron.IpcMainInvokeEvent, input: unknown): Promise<IpcResult<SessionSnapshot>> => {
    try {
      const validation = validateSessionInput(input);
      if (!validation.ok) return { ok: false, error: { code: "INVALID_SESSION_INPUT", message: validation.message } };
      return { ok: true, data: await runtime.getSession(validation.value.threadId, resume) };
    } catch (error) {
      return failure(error);
    }
  };
  ipcMain.handle(IPC_CHANNELS.sessionsGet, sessionHandler(false));
  ipcMain.handle(IPC_CHANNELS.sessionsResume, sessionHandler(true));

  const approvalHandler = (decision: "approve" | "reject") => async (_event: Electron.IpcMainInvokeEvent, input: unknown): Promise<IpcResult<RunStartResult>> => {
    try {
      const validation = validateApprovalInput(input);
      if (!validation.ok) return { ok: false, error: { code: "INVALID_APPROVAL_INPUT", message: validation.message } };
      const { threadId, approvalId, actionHash } = validation.value;
      return { ok: true, data: await runtime.resolveApproval(threadId, approvalId, actionHash, decision) };
    } catch (error) {
      return failure(error);
    }
  };
  ipcMain.handle(IPC_CHANNELS.approvalsApprove, approvalHandler("approve"));
  ipcMain.handle(IPC_CHANNELS.approvalsReject, approvalHandler("reject"));

  ipcMain.handle(IPC_CHANNELS.runsStart, async (_event, input: unknown): Promise<IpcResult<RunStartResult>> => {
    try {
      const validation = validateRunsStartInput(input);
      if (!validation.ok) {
        return { ok: false, error: { code: "INVALID_RUN_INPUT", message: validation.message, action: "Check the message and try again." } };
      }
      const data = await runtime.startRun(
        validation.value.message,
        validation.value.threadId,
        validation.value.datasetId,
      );
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

  ipcMain.handle(
    IPC_CHANNELS.filesSelect,
    async (event, input: unknown): Promise<IpcResult<DatasetSelectionResult>> => {
      try {
        const validation = validateFilesSelectInput(input);
        if (!validation.ok) {
          return {
            ok: false,
            error: {
              code: "INVALID_FILE_SELECTION_INPUT",
              message: validation.message,
              action: "Choose a CSV or XLSX file.",
            },
          };
        }
        const parent = BrowserWindow.fromWebContents(event.sender);
        const selected = parent
          ? await dialog.showOpenDialog(parent, {
              properties: ["openFile"],
              filters: [{ name: "Data files", extensions: ["csv", "xlsx"] }],
            })
          : await dialog.showOpenDialog({
              properties: ["openFile"],
              filters: [{ name: "Data files", extensions: ["csv", "xlsx"] }],
            });
        if (selected.canceled || selected.filePaths.length !== 1) {
          return { ok: true, data: { status: "cancelled" } };
        }
        const registered = await runtime.registerDataset(
          selected.filePaths[0],
          validation.value.threadId,
        );
        return {
          ok: true,
          data: {
            status: "selected",
            requestId: registered.requestId,
            threadId: registered.threadId,
            dataset: registered.dataset as unknown as DatasetSummary,
          },
        };
      } catch (error) {
        return failure(error);
      }
    },
  );
}
