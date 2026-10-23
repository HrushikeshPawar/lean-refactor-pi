import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Type, type TSchema } from "typebox";
import { render as renderText } from "./text.ts";

export interface FieldSchema {
  type: string;
  description?: string;
  required?: boolean;
  enum?: string[];
  pattern?: string;
  items?: FieldSchema;
  properties?: Record<string, FieldSchema>;
  minItems?: number;
  maxItems?: number;
  maxItemsFrom?: string;
  exclusive?: string[];
  requireOne?: boolean;
  handler?: boolean;
}

export interface ToolSchemaFile {
  roles: Record<string, string[]>;
  tools: Record<string, FieldSchema & { properties?: Record<string, FieldSchema> }>;
}

const root = resolve(import.meta.dirname, "../../..");

export function loadToolSchemas(): ToolSchemaFile {
  return JSON.parse(readFileSync(resolve(root, "agent-text/tool-schemas.json"), "utf8")) as ToolSchemaFile;
}

function limit(field: FieldSchema, numbers: Record<string, number>, key: "maxItems" | "minItems"): number | undefined {
  if (key === "maxItems") {
    if (field.maxItems !== undefined) return field.maxItems;
    const source = field.maxItemsFrom;
    return source === undefined ? undefined : numbers[source];
  }
  return field.minItems;
}

async function box(tool: string, field: FieldSchema, numbers: Record<string, number>): Promise<TSchema> {
  const description = field.description ? await renderText(`tools/${tool}.params.${field.description}`) : undefined;
  if (field.type === "string") {
    if (field.enum && field.pattern) {
      return Type.Union(
        [...field.enum.map(value => Type.Literal(value)), Type.String({ pattern: field.pattern })],
        description ? { description } : {},
      );
    }
    if (field.enum) return Type.Union(field.enum.map(value => Type.Literal(value)), description ? { description } : {});
    return Type.String(description ? { description } : {});
  }
  if (field.type === "number") return Type.Number(description ? { description } : {});
  if (field.type === "integer") return Type.Integer(description ? { description } : {});
  if (field.type === "array") {
    const items = await box(tool, field.items ?? { type: "string" }, numbers);
    const minItems = limit(field, numbers, "minItems");
    const maxItems = limit(field, numbers, "maxItems");
    return Type.Array(items, {
      ...(description ? { description } : {}),
      ...(minItems !== undefined ? { minItems } : {}),
      ...(maxItems !== undefined ? { maxItems } : {}),
    });
  }
  const properties: Record<string, TSchema> = {};
  for (const [name, child] of Object.entries(field.properties ?? {})) {
    const boxed = await box(tool, child, numbers);
    properties[name] = child.required ? boxed : Type.Optional(boxed);
  }
  return Type.Object(properties, description ? { description } : {});
}

export async function parametersFor(tool: string, schema: FieldSchema, numbers: Record<string, number>) {
  const properties: Record<string, TSchema> = {};
  for (const [name, child] of Object.entries(schema.properties ?? {})) {
    const boxed = await box(tool, child, numbers);
    properties[name] = child.required ? boxed : Type.Optional(boxed);
  }
  return Type.Object(properties);
}

export function executableTools(schemas: ToolSchemaFile, role: string): string[] {
  return schemas.roles[role].filter(name => schemas.tools[name]?.handler === true);
}
