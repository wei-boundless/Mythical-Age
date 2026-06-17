type ClassDictionary = Record<string, boolean | null | undefined>;
type ClassArray = ClassValue[];
type ClassValue = ClassArray | ClassDictionary | boolean | null | number | string | undefined;

export function cn(...values: ClassValue[]) {
  const classes: string[] = [];
  for (const value of values) {
    if (!value) {
      continue;
    }
    if (typeof value === "string" || typeof value === "number") {
      classes.push(String(value));
      continue;
    }
    if (Array.isArray(value)) {
      const nested = cn(...value);
      if (nested) {
        classes.push(nested);
      }
      continue;
    }
    for (const [key, enabled] of Object.entries(value)) {
      if (enabled) {
        classes.push(key);
      }
    }
  }
  return classes.join(" ");
}
