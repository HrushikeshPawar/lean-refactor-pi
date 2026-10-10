import { readdir, readFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function textRoot() { return process.env.ARENA_TEXT_DIR ?? resolve(dirname(fileURLToPath(import.meta.url)), "../../../agent-text"); }
const namePattern = /^[a-z][a-z0-9_]*$/;
const placeholder = /\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)(?::(d|\.\df|g))?\}/g;

export class TextError extends Error {}

function fixed(value: number, digits: number): string {
  const data = new DataView(new ArrayBuffer(8));
  data.setFloat64(0, value);
  const bits = data.getBigUint64(0);
  const negative = (bits >> 63n) === 1n;
  const exponent = Number((bits >> 52n) & 0x7ffn);
  const fraction = bits & ((1n << 52n) - 1n);
  const mantissa = exponent === 0 ? fraction : (1n << 52n) | fraction;
  const binaryExponent = exponent === 0 ? -1074 : exponent - 1023 - 52;
  let numerator = mantissa * 10n ** BigInt(digits);
  let denominator = 1n;
  if (binaryExponent >= 0) numerator <<= BigInt(binaryExponent);
  else denominator <<= BigInt(-binaryExponent);
  let rounded = numerator / denominator;
  const remainder = numerator % denominator;
  if (remainder * 2n > denominator || (remainder * 2n === denominator && rounded % 2n === 1n)) rounded++;
  const scaled = rounded.toString().padStart(digits + 1, "0");
  const body = digits ? `${scaled.slice(0, -digits)}.${scaled.slice(-digits)}` : scaled;
  return `${negative || Object.is(value, -0) ? "-" : ""}${body}`;
}

function general(value: number): string {
  const trim = (raw: string) => raw.includes(".") ? raw.replace(/0+$/, "").replace(/\.$/, "") : raw;
  const rounded = Number(value.toPrecision(6));
  if (rounded === 0) return Object.is(value, -0) || value < 0 ? "-0" : "0";
  const exponent = Math.floor(Math.log10(Math.abs(rounded)));
  if (exponent < -4 || exponent >= 6) {
    const [coefficient, rawExponent] = rounded.toExponential(5).split("e");
    const power = Number(rawExponent);
    return `${trim(coefficient)}e${power >= 0 ? "+" : "-"}${String(Math.abs(power)).padStart(2, "0")}`;
  }
  return trim(rounded.toFixed(Math.max(0, 5 - exponent)));
}

function parseYaml(text: string, key: string): Record<string, unknown> {
  const rootValue: Record<string, unknown> = {};
  const stack: { indent: number; value: Record<string, unknown> }[] = [{ indent: -2, value: rootValue }];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    if (!rawLine.trim() || rawLine.trimStart().startsWith("#")) continue;
    const indent = rawLine.length - rawLine.trimStart().length;
    const line = rawLine.trim();
    if (indent % 2 || !line.includes(":")) throw new TextError(`${key}: invalid YAML line ${line}`);
    const [name, ...rest] = line.split(":");
    if (!namePattern.test(name)) throw new TextError(`${key}: invalid YAML key ${name}`);
    while (stack.at(-1)!.indent >= indent) stack.pop();
    if (indent !== stack.at(-1)!.indent + 2) throw new TextError(`${key}: invalid YAML indentation`);
    const raw = rest.join(":").trim();
    if (!raw) {
      const nested: Record<string, unknown> = {};
      stack.at(-1)!.value[name] = nested;
      stack.push({ indent, value: nested });
    } else if (raw === "|" || raw === "|-") {
      const block: string[] = [];
      while (i + 1 < lines.length && (lines[i + 1].length - lines[i + 1].trimStart().length) > indent) {
        i++;
        block.push(lines[i].slice(Math.min(indent + 2, lines[i].length)));
      }
      stack.at(-1)!.value[name] = block.join("\n") + (raw === "|" ? "\n" : "");
    } else if (raw.startsWith('"')) {
      try {
        const value: unknown = JSON.parse(raw);
        if (typeof value !== "string") throw new Error("not string");
        stack.at(-1)!.value[name] = value;
      } catch { throw new TextError(`${key}: invalid quoted scalar ${raw}`); }
    } else stack.at(-1)!.value[name] = raw;
  }
  return rootValue;
}

function flatten(value: Record<string, unknown>, prefix = ""): Record<string, string> {
  const output: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    const full = prefix ? `${prefix}.${key}` : key;
    if (typeof item === "object" && item !== null) Object.assign(output, flatten(item as Record<string, unknown>, full));
    else output[full] = String(item);
  }
  return output;
}

let cached: { templates: Map<string, string>; numeric: Record<string, number> } | undefined;
async function load() {
  if (cached) return cached;
  const templates = new Map<string, string>();
  async function walk(directory: string) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile() && entry.name.endsWith(".md") && relative(root, path) !== "README.md") {
        templates.set(relative(root, path).slice(0, -3).split("\\").join("/"), await readFile(path, "utf8"));
      }
    }
  }
  const root = textRoot();
  await walk(root);
  async function addYaml(directory: string) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) await addYaml(path);
      else if (entry.isFile() && entry.name.endsWith(".yaml") && path !== resolve(root, "numbers.yaml")) {
        const prefix = relative(root, path).slice(0, -5).split("\\").join("/");
        const flat = flatten(parseYaml(await readFile(path, "utf8"), prefix));
        for (const [key, value] of Object.entries(flat)) templates.set(`${prefix}.${key}`, value);
      }
    }
  }
  await addYaml(root);
  const numberPath = resolve(root, "numbers.yaml");
  let numeric: Record<string, number> = {};
  try {
    const raw = flatten(parseYaml(await readFile(numberPath, "utf8"), "numbers"));
    numeric = Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, Number(value)]));
    if (Object.values(numeric).some(value => !Number.isFinite(value))) throw new TextError("numbers: values must be numeric");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  cached = { templates, numeric };
  return cached;
}

function scan(key: string, source: string): { name: string; spec?: string }[] {
  const found: { name: string; spec?: string }[] = [];
  let i = 0;
  while (i < source.length) {
    if (source.startsWith("{{", i) || source.startsWith("}}", i)) i += 2;
    else if (source[i] === "}") throw new TextError(`${key}: unmatched closing brace`);
    else if (source[i] === "{") {
      placeholder.lastIndex = i;
      const match = placeholder.exec(source);
      if (!match) throw new TextError(`${key}: invalid placeholder near ${source.slice(i, i + 20)}`);
      found.push({ name: match[1], spec: match[2] });
      i = placeholder.lastIndex;
    } else i++;
  }
  return found;
}

export async function keys(): Promise<string[]> { return [...(await load()).templates.keys()].sort(); }
export function clearCache() { cached = undefined; }
export async function template(key: string): Promise<string> {
  const value = (await load()).templates.get(key);
  if (value === undefined) throw new TextError(`${key}: unknown template key`);
  scan(key, value);
  return value;
}
export async function numbers(): Promise<Record<string, number>> { return { ...(await load()).numeric }; }

export async function render(key: string, values: Record<string, unknown> = {}): Promise<string> {
  const source = await template(key);
  const placeholders = scan(key, source);
  const constants = (await load()).numeric;
  const names = new Set(placeholders.map(item => item.name));
  const collision = Object.keys(values).find(name => name in constants);
  if (collision) throw new TextError(`${key}: value '${collision}' collides with numbers.yaml`);
  const missing = [...names].find(name => !(name in values) && !(name in constants));
  if (missing) throw new TextError(`${key}: missing placeholder '${missing}'`);
  const unused = Object.keys(values).find(name => !names.has(name));
  if (unused) throw new TextError(`${key}: unused value '${unused}'`);
  const protectedSource = source.replaceAll("{{", "\0OPEN\0").replaceAll("}}", "\0CLOSE\0");
  const rendered = protectedSource.replace(placeholder, (_all, name: string, spec?: string) => {
    const value = name in values ? values[name] : constants[name];
    if (!spec) return String(value);
    if (typeof value !== "number") throw new TextError(`${key}: cannot format placeholder '${name}' with '${spec}'`);
    if (spec === "d") {
      if (!Number.isInteger(value)) throw new TextError(`${key}: cannot format placeholder '${name}' with '${spec}'`);
      return String(value);
    }
    if (spec === "g") return general(value);
    return fixed(value, Number(spec.slice(1, -1)));
  });
  return rendered.replaceAll("\0OPEN\0", "{").replaceAll("\0CLOSE\0", "}");
}
