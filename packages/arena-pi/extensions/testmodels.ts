// Test helper: budget.ts reads models.yaml through ARENA_MODELS_JSON, which the Python runner normally
// sets. Import this first in a test file so the environment is ready before budget.ts loads.
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../..");
process.env.ARENA_MODELS_JSON ??= execFileSync("uv",
  ["run", "--no-project", "python", "-c", "from arena import models; print(models.pi_json())"],
  { cwd: root, encoding: "utf8" }).trim();
