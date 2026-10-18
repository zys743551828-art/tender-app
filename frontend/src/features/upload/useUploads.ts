import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/endpoints';
import type { FileRole, FileVersion } from '../../api/types';
import { fileKeys } from '../materials/queries';
import { fetchPutPart, Uploader, type UploadState } from './uploader';

export interface UploadItem {
  id: number;
  name: string;
  role: FileRole;
  /** 作为该已有文件的新版本；null 表示新文件。 */
  versionOfFileId: string | null;
  uploader: Uploader;
  state: UploadState;
  /** 服务端返回的是资料清单里本来就有的版本（内容相同的重复上传），没有产生新版本。 */
  duplicate: boolean;
}

/** 管理一个项目页内的多个上传；每个文件一个 Uploader 状态机，React 只订阅其快照。 */
export function useUploads(projectId: string) {
  const qc = useQueryClient();
  const [items, setItems] = useState<UploadItem[]>([]);
  const seq = useRef(0);
  const unsubs = useRef(new Map<number, () => void>());

  useEffect(() => {
    const subs = unsubs.current;
    return () => {
      for (const u of subs.values()) u();
      subs.clear();
    };
  }, []);

  const add = useCallback(
    (
      file: File,
      role: FileRole,
      versionOfFileId: string | null = null,
      sourceWordVersionId: string | null = null,
    ) => {
      const id = ++seq.current;
      const uploader = new Uploader(
        {
          init: (b, o) => api.uploads.init(projectId, b, o),
          refreshUrls: (uploadId) => api.uploads.refreshUrls(uploadId),
          complete: (uploadId, b, o) => api.uploads.complete(uploadId, b, o),
          putPart: (url, body, signal) => fetchPutPart(url, body, signal),
        },
        { file, role, versionOfFileId, sourceWordVersionId },
      );
      const item: UploadItem = {
        id,
        name: file.name,
        role,
        versionOfFileId,
        uploader,
        state: uploader.getState(),
        duplicate: false,
      };
      setItems((xs) => [...xs, item]);
      unsubs.current.set(
        id,
        uploader.subscribe((state) => {
          let duplicate = false;
          if (state.phase === 'done' && state.version) {
            // 必须在刷新清单之前判断：返回的版本已在清单里，说明没有产生新版本。
            const known = qc.getQueryData<FileVersion[]>(fileKeys.list(projectId));
            duplicate = known?.some((f) => f.version_id === state.version?.version_id) ?? false;
          }
          setItems((xs) =>
            xs.map((x) => (x.id === id ? { ...x, state, duplicate: x.duplicate || duplicate } : x)),
          );
          if (state.phase === 'done') {
            // 上传即评审：资料入库后流水线随即启动，顶部进度条要马上看到。
            void qc.invalidateQueries({ queryKey: fileKeys.list(projectId) });
            void qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] });
            void qc.invalidateQueries({ queryKey: ['projects', projectId, 'pipeline'] });
            void qc.invalidateQueries({ queryKey: ['projects', projectId, 'report'] });
          }
        }),
      );
      void uploader.start();
    },
    [projectId, qc],
  );

  const remove = useCallback((id: number) => {
    setItems((xs) => {
      xs.find((x) => x.id === id)?.uploader.cancel();
      return xs.filter((x) => x.id !== id);
    });
    unsubs.current.get(id)?.();
    unsubs.current.delete(id);
  }, []);

  return { items, add, remove };
}
