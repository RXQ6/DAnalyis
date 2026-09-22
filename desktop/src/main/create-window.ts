import { BrowserWindow } from "electron";
import { join } from "node:path";
import { secureWebPreferences } from "./window-options";

export async function createWindow(
  options: { show?: boolean } = {},
): Promise<BrowserWindow> {
  const window = new BrowserWindow({
    width: 800,
    height: 600,
    show: options.show ?? true,
    webPreferences: secureWebPreferences(
      join(__dirname, "..", "preload", "index.js"),
    ),
  });

  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  await window.loadFile(join(__dirname, "..", "renderer", "index.html"));
  return window;
}
