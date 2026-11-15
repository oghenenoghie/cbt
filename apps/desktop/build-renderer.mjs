// Bundles the lab app's screens (src/renderer) into dist/renderer: one script, its styles and the
// page. The main process and the core are compiled by tsc (tsconfig.json).
import { build } from "esbuild";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";

// `--production` (the installer build) minifies and leaves out source maps.
const production = process.argv.includes("--production") || process.env.NODE_ENV === "production";

rmSync("dist/renderer", { recursive: true, force: true });
mkdirSync("dist/renderer", { recursive: true });
await build({
  entryPoints: ["src/renderer/main.tsx"],
  bundle: true,
  outfile: "dist/renderer/app.js",
  format: "iife",
  platform: "browser",
  target: "chrome130",
  jsx: "automatic",
  minify: production,
  sourcemap: !production,
  define: { "process.env.NODE_ENV": JSON.stringify(production ? "production" : "development") },
  logLevel: "warning",
});
copyFileSync("src/renderer/index.html", "dist/renderer/index.html");
copyFileSync("src/renderer/styles.css", "dist/renderer/styles.css");
