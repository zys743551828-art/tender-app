import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import { ErrorNotice, Loading, Notice } from '../../components/ui';
import { Button, textLink } from '../../components/ui/button';

export function TableStructures({
  projectId,
  versionId,
  parseId,
}: {
  projectId: string;
  versionId: string;
  parseId: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [table, setTable] = useState(0);
  const [row, setRow] = useState(0);
  const q = useQuery({
    queryKey: ['table-structures', versionId, parseId, table, row],
    queryFn: () => api.recognition.tables(versionId, table, row, parseId),
    enabled: open,
  });
  const pageLink = (page: number) =>
    `/projects/${projectId}/files/${versionId}?page=${String(page)}&verify=1`;
  return (
    <div className="space-y-3 border-t border-border pt-3">
      <Button onClick={() => setOpen(!open)} aria-expanded={open}>
        查看表格结构候选
      </Button>
      {open ? (
        <>
          <p className="text-sm text-muted-foreground">
            原始识别结构仅供对照，摘录订正不会改写此表格。空格不代表原件为空，需核对行列、数字和单位；可能续表不会自动合并。
          </p>
          {q.isPending ? <Loading /> : null}
          {q.isError ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : null}
          {q.data?.state === 'not_evaluated' ? (
            <Notice>此解析未执行结构候选检查，请保留原报告并在需要时重新解析资料。</Notice>
          ) : null}
          {q.data?.state === 'candidate_preview' ? (
            <>
              <p>
                共 {q.data.table_count}{' '}
                张结构候选；仅检查已选择的解析页，未找到候选不表示原件没有表格。
              </p>
              {q.data.table_id && q.data.physical_page !== null ? (
                <>
                  <p>
                    第 {table + 1} 张 ·{' '}
                    {q.data.source === 'raster_grid' ? '扫描网格与 OCR 归属' : '原生表格'} ·
                    待人工核对
                  </p>
                  <Link className={textLink} to={pageLink(q.data.physical_page)}>
                    对照表格原页第 {q.data.physical_page} 页
                  </Link>
                  {q.data.unassigned_line_indices.length ? (
                    <Notice>
                      有 {q.data.unassigned_line_indices.length} 行 OCR
                      跨格或归属不明，未填入单元格；请对照原页及逐条 OCR 候选。
                    </Notice>
                  ) : null}
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-sm" aria-label="原始表格结构候选">
                      <caption className="text-left">
                        共 {q.data.row_count} 行，当前从第 {q.data.row_offset + 1} 行展示，最多 20
                        行
                      </caption>
                      <tbody>
                        {q.data.rows.map((cells, r) => (
                          <tr key={r}>
                            {cells.map((cell, c) => (
                              <td key={c} className="whitespace-pre-wrap border border-border p-2">
                                {cell?.trim() ? (
                                  cell
                                ) : (
                                  <span className="text-muted-foreground">未识别</span>
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button disabled={row === 0} onClick={() => setRow(Math.max(0, row - 20))}>
                      上一组表格行
                    </Button>
                    <Button
                      disabled={q.data.next_row_offset === null}
                      onClick={() => setRow(q.data?.next_row_offset ?? 0)}
                    >
                      下一组表格行
                    </Button>
                  </div>
                  {q.data.continuations.map((link) => (
                    <Notice key={`${link.from_table_id}:${link.to_table_id}`}>
                      可能续表：相邻页重复表头且列位置一致，关系尚未确认。
                      <Link className={textLink} to={pageLink(link.from_page)}>
                        对照第 {link.from_page} 页
                      </Link>{' '}
                      <Link className={textLink} to={pageLink(link.to_page)}>
                        对照第 {link.to_page} 页
                      </Link>
                    </Notice>
                  ))}
                </>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={table === 0}
                  onClick={() => {
                    setTable(table - 1);
                    setRow(0);
                  }}
                >
                  上一张表格
                </Button>
                <Button
                  disabled={table + 1 >= q.data.table_count}
                  onClick={() => {
                    setTable(table + 1);
                    setRow(0);
                  }}
                >
                  下一张表格
                </Button>
              </div>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
