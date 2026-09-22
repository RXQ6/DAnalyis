import type { FilesSelectInput } from "../../shared/ipc";

type ValidationResult =
  | { ok: true; value: FilesSelectInput }
  | { ok: false; message: string };

export function validateFilesSelectInput(input: unknown): ValidationResult {
  if (input === undefined) return { ok: true, value: {} };
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return { ok: false, message: "Input must be an object." };
  }
  const value = input as Record<string, unknown>;
  if (Object.keys(value).some((key) => key !== "threadId")) {
    return { ok: false, message: "Input may only contain threadId." };
  }
  if (
    value.threadId !== undefined &&
    (typeof value.threadId !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.threadId))
  ) {
    return { ok: false, message: "threadId is invalid." };
  }
  return {
    ok: true,
    value: typeof value.threadId === "string" ? { threadId: value.threadId } : {},
  };
}
