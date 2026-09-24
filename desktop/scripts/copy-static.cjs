const { cpSync, mkdirSync, readFileSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");

const root = join(__dirname, "..");
const rendererOutput = join(root, "dist", "src", "renderer");

mkdirSync(rendererOutput, { recursive: true });
cpSync(
  join(root, "src", "renderer", "index.html"),
  join(rendererOutput, "index.html"),
);
cpSync(
  join(root, "src", "renderer", "styles.css"),
  join(rendererOutput, "styles.css"),
);
cpSync(
  join(root, "assets", "brand"),
  join(rendererOutput, "assets"),
  { recursive: true },
);

const modules = ["presentation", "chart-renderer", "run-state", "trace-panel", "product-state", "index"];
const factories = modules.map((name) => {
  const source = readFileSync(join(rendererOutput, `${name}.js`), "utf8");
  return `define("./${name}", function (require, module, exports) {\n${source}\n});`;
});
const bundle = `(function () {
  "use strict";
  const factories = new Map();
  const cache = new Map();
  function define(id, factory) { factories.set(id, factory); }
  function load(id) {
    if (cache.has(id)) return cache.get(id).exports;
    const factory = factories.get(id);
    if (!factory) throw new Error("Unknown renderer module: " + id);
    const module = { exports: {} };
    cache.set(id, module);
    factory(load, module, module.exports);
    return module.exports;
  }
  ${factories.join("\n")}
  load("./index");
})();\n`;
writeFileSync(join(rendererOutput, "bundle.js"), bundle, "utf8");
