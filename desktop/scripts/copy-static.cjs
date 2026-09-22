const { cpSync, mkdirSync } = require("node:fs");
const { join } = require("node:path");

const root = join(__dirname, "..");
const rendererOutput = join(root, "dist", "src", "renderer");

mkdirSync(rendererOutput, { recursive: true });
cpSync(
  join(root, "src", "renderer", "index.html"),
  join(rendererOutput, "index.html"),
);

