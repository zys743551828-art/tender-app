import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../../api/endpoints';
import { ErrorNotice, Loading, PageHead } from '../../components/ui';
import { evidenceKindLabel } from '../../lib/labels';
import { useFiles } from '../materials/queries';
import { useProjectContext } from '../../routes/ProjectLayout';
import { PdfViewer } from './PdfViewer';
import { Icon } from '../../components/Icon';
import { Button } from '../../components/ui/button';

/** 单条证据的原页查看：/projects/:id/evidence/:evidenceId */
export function EvidencePage() {
  const { evidenceId = '' } = useParams();
  const { project } = useProjectContext();
  const q = useQuery({
    queryKey: ['evidence', evidenceId],
    queryFn: () => api.evidence.get(evidenceId),
  });
  const files = useFiles(project.project_id);
  const file = files.data?.find((f) => f.version_id === q.data?.version_id);

  return (
    <>
      <PageHead
        title="证据原页"
        lede="原件对应页，摘录位置已高亮；定位不到坐标时只显示整页。"
        actions={
          <Button asChild>
            <Link to={`/projects/${project.project_id}/findings`}>返回问题列表</Link>
          </Button>
        }
      />
      {q.isPending ? <Loading /> : null}
      {q.isError ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : null}
      {q.data ? (
        <div>
          <p className="m-0 mb-3 flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <Icon name="FileText" size={14} />
            {file ? file.original_name : q.data.file_name} · 第 {q.data.physical_page} 页 ·{' '}
            {evidenceKindLabel(q.data.kind)}
          </p>
          <PdfViewer
            versionId={q.data.version_id}
            page={q.data.physical_page}
            printedPage={q.data.printed_page}
            bbox={q.data.bbox}
            quote={q.data.quote}
          />
        </div>
      ) : null}
    </>
  );
}

/** 整份原件查看：/projects/:id/files/:versionId?page=N */
export function FileViewerPage() {
  const { versionId = '' } = useParams();
  const [sp] = useSearchParams();
  const { project } = useProjectContext();
  const files = useFiles(project.project_id);
  const file = files.data?.find((f) => f.version_id === versionId);
  const page = Math.max(1, Number(sp.get('page')) || 1);
  return (
    <>
      <PageHead
        title="原件查看"
        lede={file ? file.original_name : `文件版本 ${versionId}`}
        actions={
          <Button asChild>
            <Link to={`/projects/${project.project_id}/materials`}>返回资料列表</Link>
          </Button>
        }
      />
      <PdfViewer versionId={versionId} page={page} bbox={null} />
    </>
  );
}
