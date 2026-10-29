import { it, expect } from "vitest";
import {
  uploadMediaType,
  sameUploadFormat,
  wordMediaType,
} from "./uploadFormats";
it("DOCX固定OOXML媒体，不依赖浏览器空type；Word与PDF不能选为同一逻辑文件版本", () => {
  expect(uploadMediaType("修改稿.DOCX")).toBe(wordMediaType);
  expect(uploadMediaType("扫描.pdf")).toBe("application/pdf");
  expect(sameUploadFormat("正文.pdf", "正文.docx")).toBe(false);
  expect(sameUploadFormat("正文.docx", "正文v2.DOCX")).toBe(true);
  expect(() => uploadMediaType("旧文档.doc")).toThrow(/另存为DOCX/);
});
