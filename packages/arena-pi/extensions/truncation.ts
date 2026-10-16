export function buildTurnCutLine(outputTokens: number, template: string): string {
  return template.replace("{tokens}", String(outputTokens));
}
