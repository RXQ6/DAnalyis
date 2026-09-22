import type { RunsCancelInput } from "../../shared/ipc";

type ValidationResult =
  | { ok: true; value: RunsCancelInput }
  | { ok: false; message: string };

export function validateRunsCancelInput(input: unknown): ValidationResult {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return { ok: false, message: "Input must be an object." };
  }
  const value = input as Record<string, unknown>;
  if (Object.keys(value).length !== 1 || typeof value.runId !== "string") {
    return { ok: false, message: "Input must contain only runId." };
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.runId)) {
    return { ok: false, message: "runId is invalid." };
  }
  return { ok: true, value: { runId: value.runId } };
}
