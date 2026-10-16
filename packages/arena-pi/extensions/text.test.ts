import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import * as text from "./text.ts";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

test("shared renderer cases", async () => {
  const cases = JSON.parse(await readFile(resolve(repo, "tests/fixtures/text-cases.json"), "utf8"));
  for (const [index, item] of cases.entries()) {
    const directory = await mkdtemp(resolve(tmpdir(), "arena-text-"));
    const previous = process.env.ARENA_TEXT_DIR;
    try {
      process.env.ARENA_TEXT_DIR = directory;
      for (const [name, content] of Object.entries(item.files as Record<string, string>)) {
        const path = resolve(directory, name);
        await mkdir(dirname(path), { recursive: true });
        await writeFile(path, content);
      }
      text.clearCache();
      if (item.error) {
        await assert.rejects(text.render(item.key, item.values ?? {}),
          error => error instanceof Error && error.message.includes(item.error), `case ${index}`);
      } else assert.equal(await text.render(item.key, item.values ?? {}), item.expect, `case ${index}`);
    } finally {
      text.clearCache();
      if (previous === undefined) delete process.env.ARENA_TEXT_DIR;
      else process.env.ARENA_TEXT_DIR = previous;
      await rm(directory, { recursive: true, force: true });
    }
  }
});
