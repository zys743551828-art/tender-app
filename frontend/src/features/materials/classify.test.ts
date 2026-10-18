import { describe, expect, it } from 'vitest';
import type { FileGroup } from './queries';
import { defaultTarget, guessRole } from './classify';

const group = (fileId: string, role: FileGroup['role'], name: string): FileGroup =>
  ({
    fileId,
    role,
    names: [name],
    versionNo: 1,
    latest: { original_name: name },
  }) as unknown as FileGroup;

describe('guessRole', () => {
  it('按文件名关键词判断用途', () => {
    expect(guessRole('XX道路工程招标文件.pdf', [])).toBe('tender');
    expect(guessRole('补遗书（一）.pdf', [])).toBe('supplement');
    expect(guessRole('施工组织设计-第二版.pdf', [])).toBe('body');
    expect(guessRole('技术标.docx', [])).toBe('body');
    expect(guessRole('工程量清单.xlsx', [])).toBe('boq');
    expect(guessRole('总平面图纸.pdf', [])).toBe('drawing');
  });

  it('没命中时：还没有招标文件就当招标文件，否则当施组正文；带来的用途优先', () => {
    expect(guessRole('scan001.pdf', [])).toBe('tender');
    expect(guessRole('scan001.pdf', [group('f1', 'tender', 'a.pdf')])).toBe('body');
    expect(guessRole('招标文件.pdf', [], 'body')).toBe('body');
  });
});

describe('defaultTarget', () => {
  it('Word 和 PDF 各自选择版本链，转换 PDF 不参与原稿默认目标', () => {
    const groups = [group('pdf', 'body', '施组.pdf')];
    expect(defaultTarget('施组.docx', 'body', groups)).toBeNull();
    expect(defaultTarget('施组.pdf', 'body', [group('word', 'body', '施组.docx')])).toBeNull();
    expect(
      defaultTarget('施组-二.docx', 'body', [group('word', 'body', '施组.docx'), ...groups]),
    ).toBe('word');
  });
  it('同用途同名 → 该文件的新版本；唯一一份正文 → 正文的新版本；其余为新文件', () => {
    const groups = [group('f1', 'tender', '招标文件.pdf'), group('f2', 'body', '施组.pdf')];
    expect(defaultTarget('招标文件.pdf', 'tender', groups)).toBe('f1');
    expect(defaultTarget('招标文件-补充.pdf', 'tender', groups)).toBeNull();
    expect(defaultTarget('施组-改.pdf', 'body', groups)).toBe('f2');
    expect(
      defaultTarget('施组-改.pdf', 'body', [...groups, group('f3', 'body', 'b.pdf')]),
    ).toBeNull();
  });
});
