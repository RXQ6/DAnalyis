import { join, resolve } from "node:path";

export interface RuntimePaths {
  repoRoot: string;
  bridgeScriptPath: string;
  workingDirectory: string;
  runtimeDataDirectory: string;
  pythonExecutable?: string;
  pythonHome?: string;
  nodeBinDirectory?: string;
}

export function resolveRuntimePaths(
  isPackaged: boolean,
  mainDirectory: string,
  resourcesDirectory: string,
  userDataDirectory: string,
): RuntimePaths {
  const repoRoot = isPackaged
    ? resourcesDirectory
    : resolve(mainDirectory, "../../../..");
  return {
    repoRoot,
    bridgeScriptPath: isPackaged
      ? join(resourcesDirectory, "desktop", "python", "runtime_bridge.py")
      : join(repoRoot, "desktop", "python", "runtime_bridge.py"),
    workingDirectory: repoRoot,
    runtimeDataDirectory: join(userDataDirectory, "runtime"),
    ...(isPackaged ? {
      pythonExecutable: join(resourcesDirectory, "python-runtime", "python.exe"),
      pythonHome: join(resourcesDirectory, "python-runtime"),
      nodeBinDirectory: join(resourcesDirectory, "bin"),
    } : {}),
  };
}
