import { Link } from 'react-router-dom';
import { Notice } from '../../components/ui';
import { textLink } from '../../components/ui/button';

/**
 * 任务在等待补充事实。后端不会因为录入了事实就自动续跑，所以如实说明下一步：
 * 录入事实 → 到报告重新评审（旧任务可取消）。
 */
export function WaitingInputNotice({ projectId }: { projectId: string }) {
  return (
    <Notice>
      任务在等待补充事实：请到
      <Link className={textLink} to={`/projects/${projectId}/basis?tab=facts`}>
        “依据”页的事实库
      </Link>
      录入后，回到“报告”点击“重新评审”；本任务不会自动继续，可以取消。
    </Notice>
  );
}
