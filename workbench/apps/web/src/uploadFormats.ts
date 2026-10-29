export const wordMediaType =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
export function uploadMediaType(filename: string) {
  if (/\.pdf$/i.test(filename)) return "application/pdf";
  if (/\.docx$/i.test(filename)) return wordMediaType;
  throw new Error("请选择PDF或DOCX文件；旧版DOC需另存为DOCX或导出PDF。");
}
export function sameUploadFormat(left: string, right: string) {
  try {
    return uploadMediaType(left) === uploadMediaType(right);
  } catch {
    return false;
  }
}
