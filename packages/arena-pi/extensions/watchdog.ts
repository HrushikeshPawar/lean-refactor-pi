// Stream idle watchdog: a provider request that shows no streamed progress for idleMs is aborted once.
// Pi's own idle timeout can be defeated by proxy keepalive bytes, so progress is counted by assistant events.
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

// An assistant stream event counts as progress when it carries content: a block start or end, or a delta with
// visible characters. Empty or whitespace deltas (a proxy padding the stream) do not reset the idle window.
export function carriesProgress(update: { type: string; delta?: unknown }): boolean {
  return typeof update.delta !== "string" || update.delta.trim().length > 0;
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
