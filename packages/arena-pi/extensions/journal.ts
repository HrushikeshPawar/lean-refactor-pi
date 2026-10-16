// Every provider request is journaled twice (the post-hook payload and the wire body), each almost a copy of the
// previous request's. A DeltaChain stores a row as the bytes between the prefix and suffix it shares with the
// previous row of its chain, with a full keyframe first and every KEYFRAME_EVERY rows. The sha256 of the full
// bytes is always kept. arena/traces.py `expand_journal` restores the originals and checks the hash.
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

export const KEYFRAME_EVERY = 25;

export type Delta = { prefix: number; suffix: number; middle: string };

const continuation = (byte: number | undefined) => byte !== undefined && (byte & 0xc0) === 0x80;

/** What turns `previous` into `current`: keep `prefix` leading and `suffix` trailing bytes of previous, insert `middle`. */
export function deltaBytes(previous: Buffer, current: Buffer): Delta {
  const limit = Math.min(previous.length, current.length);
  let prefix = 0;
  while (prefix < limit && previous[prefix] === current[prefix]) prefix += 1;
  // Cut only at character boundaries so `middle` stays valid UTF-8.
  while (prefix > 0 && continuation(current[prefix])) prefix -= 1;
  let suffix = 0;
  while (suffix < limit - prefix && previous[previous.length - 1 - suffix] === current[current.length - 1 - suffix]) suffix += 1;
  while (suffix > 0 && continuation(current[current.length - suffix])) suffix -= 1;
  return { prefix, suffix, middle: current.subarray(prefix, current.length - suffix).toString("utf8") };
}

export function applyDelta(previous: Buffer, delta: Delta): Buffer {
  return Buffer.concat([previous.subarray(0, delta.prefix), Buffer.from(delta.middle, "utf8"),
    previous.subarray(previous.length - delta.suffix)]);
}

export const sha256 = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");

export type RequestParts = {
  system: string;
  skill: string;
  tools: string;
  packet: string;
  messages: unknown[];
};

const EMPTY_PARTS: RequestParts = { system: "", skill: "", tools: "", packet: "", messages: [] };

function blockText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const block of content) {
    if (typeof block === "string") parts.push(block);
    else if (block && typeof block === "object" && typeof (block as { text?: unknown }).text === "string") {
      parts.push((block as { text: string }).text);
    }
  }
  return parts.join("\n");
}

const ADDENDUM = "<addendum>";
const ADDENDUM_END = "</addendum>";

function splitTags(text: string): { system: string; skill: string } {
  const start = text.indexOf(ADDENDUM);
  if (start < 0) return { system: text, skill: "" };
  const end = text.indexOf(ADDENDUM_END, start + ADDENDUM.length);
  return { system: text.slice(0, start), skill: end >= 0 ? text.slice(start + ADDENDUM.length, end) : "" };
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

/** Split an OpenAI chat post-hook payload (`messages`, `tools`) into the four stored texts. `system` is the
 *  text of `messages[0]` before `<addendum>`, `skill` the text between the addendum markers, `packet` the first
 *  user message, `tools` the JSON of `tools`. A payload that does not match returns empty parts; never throws. */
export function splitRequest(payload: unknown): RequestParts {
  const body = asRecord(payload);
  if (!body) return { ...EMPTY_PARTS };
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const first = asRecord(messages[0]);
  const { system, skill } = first?.role === "system" ? splitTags(blockText(first.content)) : { system: "", skill: "" };
  const user = messages.find(message => asRecord(message)?.role === "user");
  const packet = user ? blockText(asRecord(user)?.content) : "";
  let tools = "";
  if ("tools" in body && body.tools !== undefined) {
    try { tools = JSON.stringify(body.tools); } catch { tools = ""; }
  }
  return { system, skill, tools, packet, messages };
}

/** Add `turn` and, when a request is open, `request_id`. Keys already on the row stay as they are. */
export function stampRecord(row: Record<string, unknown>, turn: number, requestId?: string): Record<string, unknown> {
  const stamped = { ...row };
  if (!("turn" in stamped)) stamped.turn = turn;
  if (requestId !== undefined && !("request_id" in stamped)) stamped.request_id = requestId;
  return stamped;
}

/** Content-addressed text files. `put` writes `<directory>/<sha256>` only when that file is absent. */
export class BlobStore {
  private directory: string;

  constructor(directory: string) {
    this.directory = directory;
  }

  put(text: string): string {
    const bytes = Buffer.from(text, "utf8");
    const hash = sha256(bytes);
    const target = resolve(this.directory, hash);
    if (existsSync(target)) return hash;
    mkdirSync(this.directory, { recursive: true });
    const temporary = resolve(this.directory, `.${hash}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`);
    writeFileSync(temporary, bytes, { mode: 0o600 });
    if (existsSync(target)) {
      unlinkSync(temporary);
      return hash;
    }
    renameSync(temporary, target);
    return hash;
  }
}

export class DeltaChain {
  private previous: Buffer | undefined;
  private rows = 0;

  /** `delta` is undefined for a keyframe: the caller then stores the full bytes. */
  encode(bytes: Buffer): { sha256: string; delta?: Delta } {
    const hash = sha256(bytes);
    const keyframe = this.previous === undefined || this.rows >= KEYFRAME_EVERY;
    const delta = keyframe ? undefined : deltaBytes(this.previous!, bytes);
    this.rows = keyframe ? 1 : this.rows + 1;
    this.previous = bytes;
    return { sha256: hash, delta };
  }
}
