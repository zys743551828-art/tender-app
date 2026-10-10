import { useMemo, useRef, useState, type DragEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { FILE_ROLES, type FileRole, type FileVersion, type Task } from '../../api/types';
import { Icon } from '../../components/Icon';
import {
  Alert,
  ErrorNotice,
  Loading,
  Notice,
  PageHead,
  ProgressBar,
  Tag,
} from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { cn } from '../../lib/cn';
import { formatBytes, formatDateTime } from '../../lib/format';
import { fileRoleLabel, taskStateLabel } from '../../lib/labels';
import { useProjectContext } from '../../routes/ProjectLayout';
import { MAX_FILE_BYTES, type UploadPhase } from '../upload/uploader';
import { useUploads, type UploadItem } from '../upload/useUploads';
import { STATE_TONE, errorHint } from '../tasks/shared';
import { useProjectTasks } from '../tasks/queries';
import { defaultTarget, guessRole } from './classify';
import { groupFiles, useFiles, versionNumberOf, type FileGroup } from './queries';
import { PARSED_ROLES, extractReadiness, parseTaskByVersion } from './parse';
import { PipelineBanner } from '../report/PipelineBanner';
import { usePipeline } from '../report/queries';
import { Button, buttonVariants, textLink } from '../../components/ui/button';
import { Select } from '../../components/ui/input';

/** 上传时可选的用途：官方结果在“提交与结果”里登记，不在这里上传。 */
const UPLOAD_ROLES = FILE_ROLES.filter((r) => r !== 'official_result');

const PHASE_TEXT: Record<UploadPhase, string> = {
  idle: '等待开始',
  hashing: '准备中',
  initializing: '准备中',
  uploading: '正在上传',
  completing: '正在校验',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

interface Staged {
  key: number;
  file: File;
  role: FileRole;
  /** 记为哪个已有文件的新版本；null 为新文件。 */
  target: string | null;
}

/**
 * 资料：把文件拖进来即可。系统按文件名猜用途、判断是不是已有文件的新版本，上传前可以逐个改；
 * 招标文件和施组正文齐了自动评审。
 */
export function MaterialsPage() {
  const { project } = useProjectContext();
  const files = useFiles(project.project_id);
  const uploads = useUploads(project.project_id);
  const pipeline = usePipeline(project.project_id);
  const [sp] = useSearchParams();
  // 从其他页面带着用途跳来（例如 ?role=body：上传修改后的正文）。
  const hint = FILE_ROLES.find((r) => r === sp.get('role')) ?? null;
  const tasks = useProjectTasks(project.project_id);
  const parse = useMemo(
    () => parseTaskByVersion(files.data ?? [], tasks.data ?? []),
    [files.data, tasks.data],
  );
  const readiness = extractReadiness(files.data ?? [], parse);
  const groups = useMemo(() => groupFiles(files.data ?? []), [files.data]);
  const [staged, setStaged] = useState<Staged[]>([]);
  const seq = useRef(0);
  const [localError, setLocalError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (list: FileList | null) => {
    setLocalError(null);
    if (!list) return;
    const next: Staged[] = [];
    for (const f of Array.from(list)) {
      if (f.size === 0) {
        setLocalError(`“${f.name}”是空文件，已跳过。`);
        continue;
      }
      if (f.size > MAX_FILE_BYTES) {
        setLocalError(`“${f.name}”超过 100 MiB。较大的图纸请按原分册拆开上传。`);
        continue;
      }
      const role = guessRole(f.name, groups, hint);
      next.push({ key: ++seq.current, file: f, role, target: defaultTarget(f.name, role, groups) });
    }
    setStaged((xs) => [...xs, ...next]);
    if (inputRef.current) inputRef.current.value = '';
  };
  const change = (key: number, patch: Partial<Staged>) => {
    setStaged((xs) => xs.map((x) => (x.key === key ? { ...x, ...patch } : x)));
  };
  const start = () => {
    for (const x of staged) uploads.add(x.file, x.role, x.target);
    setStaged([]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    pick(e.dataTransfer.files);
  };

  return (
    <>
      <PageHead title="资料" lede="招标文件和施组正文齐了会自动评审。" />
      {pipeline.data ? <PipelineBanner pipeline={pipeline.data} showSteps /> : null}
      <Card aria-labelledby="upload-h" className="mb-5">
        <CardHeader>
          <CardTitle id="upload-h">上传资料</CardTitle>
        </CardHeader>
        <CardContent>
          <div
            data-dragging={dragging || undefined}
            className={cn(
              'flex flex-col items-center gap-3 rounded-lg border border-dashed border-border-strong bg-subtle px-6 py-8 text-center transition-colors',
              'data-[dragging]:border-primary data-[dragging]:bg-primary-soft',
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => {
              setDragging(false);
            }}
            onDrop={(e) => {
              setDragging(false);
              onDrop(e);
            }}
          >
            <span
              aria-hidden="true"
              className="inline-flex size-10 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-xs"
            >
              <Icon name="Upload" size={18} />
            </span>
            <p className="m-0 text-[13px]">把招标文件、补遗、施组正文一起拖到这里，或</p>
            <label className={buttonVariants({ size: 'sm' })} htmlFor="upload-file">
              选择文件
            </label>
            <input
              id="upload-file"
              ref={inputRef}
              className="sr-only"
              type="file"
              multiple
              onChange={(e) => {
                pick(e.target.files);
              }}
            />
            <p className="m-0 text-xs text-muted-foreground">
              单个文件不超过 100 MiB；网络中断后可以接着传。
            </p>
          </div>
          {localError ? (
            <Alert tone="danger" role="alert" className="mt-4">
              {localError}
            </Alert>
          ) : null}
          {staged.length > 0 ? (
            <div className="mt-5">
              <p className="m-0 mb-2 text-[13px] text-muted-foreground">
                已按文件名判断用途，不对的可以改：
              </p>
              <ul
                className="m-0 mb-3 list-none divide-y divide-border rounded-md border border-border p-0"
                aria-label="待上传"
              >
                {staged.map((x) => (
                  <StagedRow
                    key={x.key}
                    item={x}
                    groups={groups}
                    onChange={(patch) => {
                      change(x.key, patch);
                    }}
                    onRemove={() => {
                      setStaged((xs) => xs.filter((y) => y.key !== x.key));
                    }}
                  />
                ))}
              </ul>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="primary" onClick={start}>
                  上传 {staged.length} 个文件
                </Button>
                <Button
                  onClick={() => {
                    setStaged([]);
                  }}
                >
                  全部移除
                </Button>
              </div>
            </div>
          ) : null}
          {uploads.items.length > 0 ? (
            <ul className="m-0 mt-5 grid list-none gap-2 p-0" aria-label="上传队列">
              {uploads.items.map((it) => (
                <UploadRow
                  key={it.id}
                  item={it}
                  files={files.data ?? []}
                  onRemove={() => {
                    uploads.remove(it.id);
                  }}
                />
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Card aria-labelledby="files-h" className="mb-5">
        <CardHeader>
          <CardTitle id="files-h">已上传</CardTitle>
        </CardHeader>
        <CardContent>
          {files.isPending ? <Loading /> : null}
          {files.isError ? (
            <ErrorNotice error={files.error} onRetry={() => void files.refetch()} />
          ) : null}
          {files.isSuccess && files.data.length === 0 ? (
            <p className="m-0 text-[13px] text-muted-foreground">
              还没有资料。至少需要一份招标文件和一份施组正文。
            </p>
          ) : null}
          {files.isSuccess && files.data.length > 0 ? (
            <>
              {!readiness.hasTender ? (
                <Notice>还没有招标文件，暂时不能评审。</Notice>
              ) : readiness.waiting > 0 ? (
                <p className="m-0 mb-3 text-[13px] text-muted-foreground">
                  还有 {readiness.waiting} 份招标文件／补遗正在解析，完成后自动提取规则并评审。
                </p>
              ) : null}
              <div className="relative w-full overflow-x-auto">
                <table className="data-table stack-mobile">
                  <caption className="sr-only">项目资料</caption>
                  <thead>
                    <tr>
                      <th scope="col">文件</th>
                      <th scope="col">用途</th>
                      <th scope="col">版本</th>
                      <th scope="col">上传于</th>
                      <th scope="col">解析</th>
                      <th scope="col">
                        <span className="sr-only">操作</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.data.map((f) => (
                      <FileRow
                        key={f.version_id}
                        file={f}
                        projectId={project.project_id}
                        parseTask={parse.get(f.version_id)}
                        tasksLoaded={tasks.isSuccess}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </>
  );
}

function StagedRow({
  item,
  groups,
  onChange,
  onRemove,
}: {
  item: Staged;
  groups: readonly FileGroup[];
  onChange: (patch: Partial<Staged>) => void;
  onRemove: () => void;
}) {
  const same = groups.filter((g) => g.role === item.role);
  const id = `staged-${String(item.key)}`;
  return (
    <li className="grid items-center gap-2 px-3 py-2.5 sm:grid-cols-[minmax(0,1fr)_150px_minmax(0,220px)_auto] sm:gap-3">
      <span className="flex min-w-0 items-center gap-2">
        <Icon name="FileText" size={14} className="shrink-0 text-muted-foreground" />
        <strong className="truncate text-[13px] font-medium">{item.file.name}</strong>
        <span className="shrink-0 text-xs text-muted-foreground tabular">
          {formatBytes(item.file.size)}
        </span>
      </span>
      <label className="sr-only" htmlFor={`${id}-role`}>
        {item.file.name} 的用途
      </label>
      <Select
        id={`${id}-role`}
        value={item.role}
        onChange={(e) => {
          const role = e.target.value as FileRole;
          onChange({ role, target: defaultTarget(item.file.name, role, groups) });
        }}
      >
        {UPLOAD_ROLES.map((r) => (
          <option key={r} value={r}>
            {fileRoleLabel(r)}
          </option>
        ))}
      </Select>
      <label className="sr-only" htmlFor={`${id}-target`}>
        {item.file.name} 记为
      </label>
      <Select
        id={`${id}-target`}
        value={item.target ?? ''}
        onChange={(e) => {
          onChange({ target: e.target.value || null });
        }}
      >
        <option value="">新文件</option>
        {same.map((g) => (
          <option key={g.fileId} value={g.fileId}>
            {`「${g.latest.original_name}」的第 ${String(g.versionNo + 1)} 版`}
          </option>
        ))}
      </Select>
      <Button size="sm" variant="ghost" onClick={onRemove}>
        移除
      </Button>
    </li>
  );
}

function ParseCell({
  file: f,
  task: t,
  tasksLoaded,
}: {
  file: FileVersion;
  task: Task | undefined;
  tasksLoaded: boolean;
}) {
  if (!PARSED_ROLES.includes(f.role))
    return <span className="text-muted-foreground">无需解析</span>;
  if (!t)
    return (
      <span className="text-muted-foreground">{tasksLoaded ? '暂无解析记录' : '读取中…'}</span>
    );
  return (
    <>
      <Tag tone={STATE_TONE[t.state]}>{taskStateLabel(t.state)}</Tag>
      {t.message ? <small className="text-muted-foreground">{t.message}</small> : null}
      {t.error_code ? (
        <small className="text-muted-foreground">{errorHint(t.error_code)}</small>
      ) : null}
    </>
  );
}

function FileRow({
  file: f,
  projectId,
  parseTask,
  tasksLoaded,
}: {
  file: FileVersion;
  projectId: string;
  parseTask: Task | undefined;
  tasksLoaded: boolean;
}) {
  const isPdf = f.artifact.media_type === 'application/pdf';
  return (
    <tr>
      <th scope="row" className="min-w-[200px]">
        {f.original_name}
        <small className="text-muted-foreground">{formatBytes(f.artifact.byte_size)}</small>
      </th>
      <td data-label="用途">{fileRoleLabel(f.role)}</td>
      <td data-label="版本">第 {f.version_number} 版</td>
      <td data-label="上传于">{formatDateTime(f.obtained_at)}</td>
      <td data-label="解析" className="[&>small]:mt-1">
        <ParseCell file={f} task={parseTask} tasksLoaded={tasksLoaded} />
      </td>
      <td>
        {isPdf ? (
          <Link className={textLink} to={`/projects/${projectId}/files/${f.version_id}`}>
            查看原件
          </Link>
        ) : (
          <span className="text-muted-foreground">不能在线预览</span>
        )}
      </td>
    </tr>
  );
}

function UploadRow({
  item,
  files,
  onRemove,
}: {
  item: UploadItem;
  files: readonly FileVersion[];
  onRemove: () => void;
}) {
  const s = item.state;
  const total = s.totalBytes || 1;
  const hashing = s.phase === 'hashing';
  const value = hashing ? s.hashedBytes / total : s.phase === 'done' ? 1 : s.uploadedBytes / total;
  const running = ['hashing', 'initializing', 'uploading', 'completing'].includes(s.phase);
  return (
    <li
      data-phase={s.phase}
      className={cn(
        'grid gap-2 rounded-md border border-border px-3.5 py-3',
        s.phase === 'failed' && 'border-danger-border',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <strong className="min-w-0 truncate text-[13px] font-medium">{item.name}</strong>
        <span className="flex-1 text-xs text-muted-foreground tabular">
          {fileRoleLabel(item.role)} · {formatBytes(s.totalBytes)}
        </span>
        <Tag tone={s.phase === 'done' ? 'green' : s.phase === 'failed' ? 'red' : 'gray'}>
          {PHASE_TEXT[s.phase]}
        </Tag>
      </div>
      {running || s.phase === 'failed' ? (
        <ProgressBar value={value} label={`${item.name} 进度`} />
      ) : null}
      {s.parts.some((p) => p.attempts > 1 && p.status !== 'done') && s.phase !== 'done' ? (
        <p className="m-0 text-xs text-muted-foreground">网络不稳，正在重试</p>
      ) : null}
      {s.error ? (
        <p className="m-0 text-xs font-medium text-danger-foreground" role="alert">
          {s.error}
          {s.requestId ? `（请求编号 ${s.requestId}）` : ''}
        </p>
      ) : null}
      {s.phase === 'done' && item.duplicate ? (
        <Notice tone="plain">内容和已有版本完全相同，没有产生新版本。</Notice>
      ) : s.phase === 'done' ? (
        <p className="m-0 text-xs text-muted-foreground">
          {s.version?.supersedes
            ? `已记为「${s.version.original_name}」的第 ${String(versionNumberOf(files, s.version))} 版`
            : '已上传'}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {s.phase === 'failed' || s.phase === 'cancelled' ? (
          <Button size="sm" onClick={() => void item.uploader.retry()}>
            {s.phase === 'failed' ? '重试' : '重新开始'}
          </Button>
        ) : null}
        {running ? (
          <Button
            size="sm"
            onClick={() => {
              item.uploader.cancel();
            }}
          >
            取消
          </Button>
        ) : (
          <button type="button" className={textLink} onClick={onRemove}>
            从队列移除
          </button>
        )}
      </div>
    </li>
  );
}
