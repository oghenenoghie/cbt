// Bundles the lab app's screens (src/renderer) into dist/renderer: one script, its styles and the
// page. The main process and the core are compiled by tsc (tsconfig.json).
import { build } from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync("dist/renderer", { recursive: true });
await build({
  entryPoints: ["src/renderer/main.tsx"],
  bundle: true,
  outfile: "dist/renderer/app.js",
  format: "iife",
  platform: "browser",
  target: "chrome130",
  jsx: "automatic",
  minify: process.env.NODE_ENV === "production",
  sourcemap: process.env.NODE_ENV !== "production",
  define: { "process.env.NODE_ENV": JSON.stringify(process.env.NODE_ENV ?? "development") },
  logLevel: "warning",
});
copyFileSync("src/renderer/index.html", "dist/renderer/index.html");
copyFileSync("src/renderer/styles.css", "dist/renderer/styles.css");
