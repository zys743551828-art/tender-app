const prefix = "tender:authoring:";
export function authoringStorageKey(
  memberId: string,
  bidId: string,
  draftId: string,
) {
  return `${prefix}${memberId}:${bidId}:${draftId}`;
}
export function clearAuthoringStorage(keepMemberId?: string) {
  for (const key of Object.keys(sessionStorage))
    if (
      key.startsWith(prefix) &&
      (!keepMemberId || !key.startsWith(`${prefix}${keepMemberId}:`))
    )
      sessionStorage.removeItem(key);
}
