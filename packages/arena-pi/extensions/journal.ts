// Every provider request is journaled twice (the post-hook payload and the wire body), each almost a copy of the
// previous request's. A DeltaChain stores a row as the bytes between the prefix and suffix it shares with the
// previous row of its chain, with a full keyframe first and every KEYFRAME_EVERY rows. The sha256 of the full
// bytes is always kept. arena/traces.py `expand_journal` restores the originals and checks the hash.
import { createHash } from "node:crypto";

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
