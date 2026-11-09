type BrowserStorage = Pick<Storage, "getItem" | "setItem">;
export const workbenchPreferencesKey = "rag-workbench-preferences-v1";
export const workbenchDraftsKey = "rag-workbench-drafts-v1";
export const defaultFavoriteIds = ["policy-qa", "industry-report"];

export type WorkbenchPreferences = { favorites: string[]; recent: string[] };
export type ApplicationDraft = { task: string; reference: string; requirements: string; assistantId: string; updatedAt?: string };
export const emptyApplicationDraft: ApplicationDraft = { task: "", reference: "", requirements: "", assistantId: "" };

function readObject(storage: BrowserStorage, key: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(storage.getItem(key) ?? "null");
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  } catch { return {}; }
}

export function readWorkbenchPreferences(storage: BrowserStorage): WorkbenchPreferences {
  const value = readObject(storage, workbenchPreferencesKey);
  const strings = (input: unknown) => Array.isArray(input) ? [...new Set(input.filter((item): item is string => typeof item === "string"))] : [];
  return { favorites: "favorites" in value ? strings(value.favorites) : [...defaultFavoriteIds], recent: strings(value.recent).slice(0, 5) };
}

export function saveWorkbenchPreferences(storage: BrowserStorage, preferences: WorkbenchPreferences) {
  storage.setItem(workbenchPreferencesKey, JSON.stringify(preferences));
}

export function readApplicationDraft(storage: BrowserStorage, appId: string): ApplicationDraft {
  const value = readObject(storage, workbenchDraftsKey)[appId];
  if (!value || typeof value !== "object" || Array.isArray(value)) return { ...emptyApplicationDraft };
  const fields = value as Record<string, unknown>;
  const text = (key: string) => typeof fields[key] === "string" ? fields[key] : "";
  return { task: text("task"), reference: text("reference"), requirements: text("requirements"), assistantId: text("assistantId"), updatedAt: text("updatedAt") || undefined };
}

export function saveApplicationDraft(storage: BrowserStorage, appId: string, draft: ApplicationDraft) {
  storage.setItem(workbenchDraftsKey, JSON.stringify({ ...readObject(storage, workbenchDraftsKey), [appId]: draft }));
}
