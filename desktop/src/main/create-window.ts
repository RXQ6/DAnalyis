import { BrowserWindow, Menu } from "electron";
import { join } from "node:path";
import { secureWebPreferences } from "./window-options";

export const WINDOW_CHROME = {
  titleBarStyle: "hidden" as const,
  titleBarOverlay: { color: "#f7f9f7", symbolColor: "#1d2b2a", height: 38 },
  autoHideMenuBar: true,
};

export async function createWindow(
  options: { show?: boolean } = {},
): Promise<BrowserWindow> {
  Menu.setApplicationMenu(null);
  const window = new BrowserWindow({
    width: 800,
    height: 600,
    show: false,
    ...WINDOW_CHROME,
    icon: join(__dirname, "..", "renderer", "assets", "icon.ico"),
    webPreferences: secureWebPreferences(
      join(__dirname, "..", "preload", "index.js"),
    ),
  });
  window.setMenu(null);

  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  await window.loadFile(join(__dirname, "..", "renderer", "index.html"));
  if (options.show ?? true) window.show();
  return window;
}
