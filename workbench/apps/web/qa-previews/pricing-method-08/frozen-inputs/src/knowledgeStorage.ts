import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

const prefix = "tender:knowledge:";
export const knowledgeStorageKey = (memberId: string, objectId: string) =>
  `${prefix}${memberId}:${objectId}:`;
export function clearKnowledgeStorage(keepMemberId?: string) {
  for (const key of Object.keys(sessionStorage))
    if (
      key.startsWith(prefix) &&
      (!keepMemberId || !key.startsWith(`${prefix}${keepMemberId}:`))
    )
      sessionStorage.removeItem(key);
}
export function discardKnowledgeForm(formKey: string) {
  for (const key of Object.keys(sessionStorage))
    if (key.startsWith(formKey)) sessionStorage.removeItem(key);
}
/** Local input only; never use this cache as a publication or eligibility decision. */
export function useKnowledgeInput<T>(
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw === null) return initial;
      const parsed: unknown = JSON.parse(raw);
      if (
        Array.isArray(initial)
          ? Array.isArray(parsed)
          : typeof parsed === typeof initial && parsed !== null
      )
        return parsed as T;
    } catch {
      /* Corrupt local input does not prevent reading the server. */
    }
    return initial;
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* The visible form remains editable if browser storage is unavailable. */
    }
  }, [key, value]);
  return [value, setValue];
}
