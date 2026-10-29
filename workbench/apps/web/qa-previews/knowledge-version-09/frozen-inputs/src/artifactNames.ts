export function generatedFilename(
  projectTitle: string,
  snapshotId: string,
  format: "docx" | "pdf",
) {
  const title =
    Array.from(projectTitle.replace(/[<>:"/\\|?*]/g, "_").trim())
      .map((character) => (character.charCodeAt(0) < 32 ? "_" : character))
      .slice(0, 48)
      .join("")
      .replace(/[. ]+$/, "") || "投标项目";
  return `${title}_投标正文_快照${snapshotId.slice(0, 12)}.${format}`;
}
