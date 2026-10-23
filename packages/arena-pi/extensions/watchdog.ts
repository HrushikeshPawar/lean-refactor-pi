// Stream idle watchdog: a provider request whose assistant message does not grow for idleMs is aborted once.
// Pi's own idle timeout can be defeated by proxy keepalive bytes, so progress is growth of the accumulated assistant message.
export interface WatchdogTimers {
  now: () => number;
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

const realTimers: WatchdogTimers = {
  now: () => Date.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: handle => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

// Size of an accumulated assistant message: characters of text, thinking and tool-call arguments. Proxy
// keepalives and no-op chunks leave it unchanged, so only real growth counts as progress.
export function messageSize(message: unknown): number {
  const content = (message as { content?: unknown } | undefined)?.content;
  if (!Array.isArray(content)) return 0;
  let size = 0;
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    const b = block as Record<string, unknown>;
    for (const value of [b.text, b.thinking, b.partialJson]) if (typeof value === "string") size += value.length;
    if (b.arguments !== undefined && b.partialJson === undefined) size += JSON.stringify(b.arguments)?.length ?? 0;
  }
  return size;
}

export class StreamWatchdog {
  private handle: unknown;
  private armed = false;
  private last = 0;

  // idleMs <= 0 disables the watchdog. onIdle receives the idle seconds and runs at most once per arm().
  private readonly idleMs: number;
  private readonly onIdle: (idleSeconds: number) => void;
  private readonly timers: WatchdogTimers;

  constructor(idleMs: number, onIdle: (idleSeconds: number) => void, timers: WatchdogTimers = realTimers) {
    this.idleMs = idleMs;
    this.onIdle = onIdle;
    this.timers = timers;
  }

  arm(): void {
    this.clear();
    if (!(this.idleMs > 0)) return;
    this.armed = true;
    this.last = this.timers.now();
    this.schedule(this.idleMs);
  }

  // Streamed progress: a message start or any message update.
  touch(): void {
    if (this.armed) this.last = this.timers.now();
  }

  clear(): void {
    this.armed = false;
    if (this.handle !== undefined) this.timers.clearTimeout(this.handle);
    this.handle = undefined;
  }

  private schedule(ms: number): void {
    this.handle = this.timers.setTimeout(() => {
      this.handle = undefined;
      if (!this.armed) return;
      const idle = this.timers.now() - this.last;
      if (idle < this.idleMs) return this.schedule(this.idleMs - idle);
      this.armed = false;
      this.onIdle(Math.round(idle / 1000));
    }, ms);
  }
}
