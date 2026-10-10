import { Card } from '../../components/ui/card';
import { PageHead } from '../../components/ui';
import { useProjectContext } from '../../routes/ProjectLayout';
import { EvidenceSearch } from './search';

/** 证据检索：/projects/:id/search，结果可跳到 PDF 原页。 */
export function SearchPage() {
  const { project } = useProjectContext();
  return (
    <>
      <PageHead
        title="证据检索"
        lede="在项目资料里按关键词查找原文证据。每条结果都能回到原件页码；检索结果只是候选，不代表结论。"
      />
      <Card className="mb-5 p-5">
        <EvidenceSearch projectId={project.project_id} />
      </Card>
    </>
  );
}
