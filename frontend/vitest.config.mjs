import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  esbuild: { loader: "jsx", include: /\.(js|jsx)$/, exclude: /node_modules/, jsx: "automatic" },
  test: { environment: "jsdom", globals: true, setupFiles: ["./tests/setup.js"], include: ["tests/**/*.test.js"] },
  resolve: { alias: {
    "next/router": path.resolve("tests/stubs/router.js"),
    "next/link": path.resolve("tests/stubs/link.js"),
    "next/head": path.resolve("tests/stubs/head.js"),
  } },
});
