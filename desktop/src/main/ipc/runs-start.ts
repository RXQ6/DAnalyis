import type { RunsStartInput } from "../../shared/ipc";

const MAX_MESSAGE_LENGTH = 4_000;

type ValidationResult =
  | { ok: true; value: RunsStartInput }
  | { ok: false; message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function validateRunsStartInput(input: unknown): ValidationResult {
  if (!isRecord(input)) {
    return { ok: false, message: "Input must be an object." };
  }

  const keys = Object.keys(input);
  if (keys.some((key) => key !== "message" && key !== "threadId" && key !== "datasetId")) {
    return { ok: false, message: "Input may only contain message, threadId and datasetId." };
  }

  if (typeof input.message !== "string") {
    return { ok: false, message: "message must be a string." };
  }

  const message = input.message.trim();
  if (message.length === 0) {
    return { ok: false, message: "message must not be empty." };
  }
  if (message.length > MAX_MESSAGE_LENGTH) {
    return {
      ok: false,
      message: `message must not exceed ${MAX_MESSAGE_LENGTH} characters.`,
    };
  }

  const threadId = input.threadId;
  if (
    threadId !== undefined &&
    (typeof threadId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(threadId))
  ) {
    return { ok: false, message: "threadId is invalid." };
  }

  const datasetId = input.datasetId;
  if (
    datasetId !== undefined &&
    (typeof datasetId !== "string" || !/^ds_[A-Za-z0-9_-]{1,64}$/.test(datasetId))
  ) {
    return { ok: false, message: "datasetId is invalid." };
  }

  return {
    ok: true,
    value: { message, ...(threadId ? { threadId } : {}), ...(datasetId ? { datasetId } : {}) },
  };
}
