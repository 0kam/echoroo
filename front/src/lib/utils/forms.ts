export function textOrUndefined(
  value: string | null | undefined,
): string | undefined {
  if (value == null) {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed;
}

export function numberOrUndefined(
  value: string | null | undefined,
): number | undefined {
  const text = textOrUndefined(value);
  if (text == null) {
    return undefined;
  }
  const parsed = Number(text);
  return Number.isNaN(parsed) ? undefined : parsed;
}
