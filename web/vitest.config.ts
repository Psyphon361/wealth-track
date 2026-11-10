import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Lets tests import modules that use the "@/" path alias (e.g. components/forms/schema.ts).
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
});
