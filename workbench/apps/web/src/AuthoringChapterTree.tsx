import { useEffect, useId, useRef, useState } from "react";
import type { AuthoringTreeView } from "./contracts";
import { resolveTreeMove, treeMoveKey } from "./authoringTreeMoves";
import type { TreeMoveIntent } from "./authoringTreeMoves";
export function AuthoringChapterTree({
  tree,
  sectionId,
  navigationLocked,
  moveDisabled,
  onChoose,
  onMove,
  storageKey,
}: {
  tree: AuthoringTreeView;
  sectionId?: string;
  navigationLocked: boolean;
  moveDisabled: boolean;
  onChoose: (id: string) => Promise<void>;
  onMove: (intent: TreeMoveIntent, expectedTreeKey: string) => Promise<void>;
  storageKey: string;
}) {
  const treeKey = treeMoveKey(tree),
    prefix = useId();
  const readCollapsed = () => {
    try {
      const value: unknown = JSON.parse(
        sessionStorage.getItem(storageKey) ?? "[]",
      );
      return Array.isArray(value)
        ? value.filter((x): x is string => typeof x === "string")
        : [];
    } catch {
      return [];
    }
  };
  const [folds, setFolds] = useState(() => ({
    scope: storageKey,
    ids: readCollapsed(),
  }));
  const collapsed = folds.scope === storageKey ? folds.ids : readCollapsed();
  const [form, setForm] = useState({
    sourceId: "",
    targetId: "",
    placement: "before" as TreeMoveIntent["placement"],
    key: treeKey,
    scope: storageKey,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const lifetime = useRef(0);
  useEffect(() => {
    lifetime.current += 1;
    working.current = false;
    setBusy(false);
    setError("");
    return () => {
      lifetime.current += 1;
    };
  }, [storageKey]);
  const working = useRef(false),
    sourceSelect = useRef<HTMLSelectElement>(null);
  const drag = useRef<{
    sourceId: string;
    placement: TreeMoveIntent["placement"];
    key: string;
    scope: string;
  } | null>(null);
  useEffect(() => {
    drag.current = null;
    setDropTarget(null);
  }, [treeKey, storageKey, moveDisabled, navigationLocked]);
  const locked = moveDisabled || navigationLocked || busy;
  const stale = form.key !== treeKey || form.scope !== storageKey;
  const nodes = tree.nodes.filter((n) => !n.deleted),
    byId = new Map(nodes.map((n) => [n.section_id, n]));
  const ancestors = new Set<string>();
  let selected = sectionId ? byId.get(sectionId) : undefined;
  while (selected?.parent_id && !ancestors.has(selected.parent_id)) {
    ancestors.add(selected.parent_id);
    selected = byId.get(selected.parent_id);
  }
  const children = (id: string | null) =>
    nodes
      .filter((n) => n.parent_id === id)
      .sort(
        (a, b) =>
          a.ordinal - b.ordinal || a.section_id.localeCompare(b.section_id),
      );
  function toggle(id: string) {
    const next = collapsed.includes(id)
      ? collapsed.filter((x) => x !== id)
      : [...collapsed, id];
    setFolds({ scope: storageKey, ids: next });
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      /* Optional navigation state must not block editing. */
    }
  }
  function chooseSource(id: string) {
    setForm({
      ...form,
      sourceId: id,
      targetId: stale ? "" : form.targetId,
      key: treeKey,
      scope: storageKey,
    });
    setError("");
    sourceSelect.current?.focus();
  }
  async function move(intent: TreeMoveIntent, key: string, scope: string) {
    if (locked || working.current) return;
    if (key !== treeKey || scope !== storageKey) {
      setError("章节目录已变化，请重新选择移动范围。");
      return;
    }
    try {
      resolveTreeMove(tree.nodes, intent);
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法核对移动范围。");
      return;
    }
    const ticket = lifetime.current;
    working.current = true;
    setBusy(true);
    setError("");
    try {
      await onMove(intent, key);
    } catch (e) {
      if (lifetime.current === ticket)
        setError(e instanceof Error ? e.message : "移动预览未完成，请重试。");
    } finally {
      if (lifetime.current === ticket) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  function rows(parent: string | null, depth = 0): React.ReactNode {
    if (depth >= 6) return null;
    return children(parent).map((n) => {
      const hasChildren = children(n.section_id).length > 0;
      const open =
        !collapsed.includes(n.section_id) || ancestors.has(n.section_id);
      const control = `${prefix}-${encodeURIComponent(n.section_id)}`;
      return (
        <li
          key={n.section_id}
          onDragOver={(event) => {
            event.stopPropagation();
            const held = drag.current;
            if (
              !held ||
              locked ||
              held.key !== treeKey ||
              held.scope !== storageKey
            )
              return;
            try {
              resolveTreeMove(tree.nodes, {
                sourceId: held.sourceId,
                targetId: n.section_id,
                placement: held.placement,
              });
              event.preventDefault();
              setDropTarget(n.section_id);
            } catch {
              setDropTarget(null);
            }
          }}
          onDragLeave={(event) => {
            event.stopPropagation();
            if (
              !(event.relatedTarget instanceof Node) ||
              !event.currentTarget.contains(event.relatedTarget)
            )
              setDropTarget((old) => (old === n.section_id ? null : old));
          }}
          onDrop={(event) => {
            event.preventDefault();
            event.stopPropagation();
            const held = drag.current;
            drag.current = null;
            setDropTarget(null);
            if (held)
              void move(
                {
                  sourceId: held.sourceId,
                  targetId: n.section_id,
                  placement: held.placement,
                },
                held.key,
                held.scope,
              );
          }}
        >
          <div
            className={`chapter-tree-row${dropTarget === n.section_id ? " drop-target" : ""}`}
          >
            {hasChildren ? (
              <button
                type="button"
                className="text-button chapter-fold"
                aria-label={`${open ? "收起" : "展开"}${n.title}的子章`}
                aria-expanded={open}
                aria-controls={control}
                disabled={ancestors.has(n.section_id)}
                onClick={() => toggle(n.section_id)}
              >
                {open ? "收起" : "展开"}
              </button>
            ) : (
              <span className="chapter-fold-spacer" aria-hidden="true" />
            )}
            <button
              type="button"
              className={`chapter-link${n.section_id === sectionId ? " selected" : ""}`}
              aria-current={n.section_id === sectionId ? "true" : undefined}
              disabled={navigationLocked}
              onClick={() => void onChoose(n.section_id)}
            >
              <span>{n.node_type === "appendix" ? "附" : "章"}</span>
              <div>
                {n.title}
                <small>
                  修订 {n.section_revision} · {n.plan?.planned_pages ?? "未填"}{" "}
                  预算页 ·{" "}
                  {n.plan_content_basis_state === "section_changed"
                    ? "计划基准已变化"
                    : n.plan
                      ? "已有编写计划"
                      : "未建计划"}
                </small>
              </div>
            </button>
            <button
              type="button"
              className="text-button chapter-move-handle"
              aria-label={`选择移动章节：${n.title}`}
              disabled={locked}
              draggable={!locked}
              onClick={() => chooseSource(n.section_id)}
              onDragStart={(event) => {
                if (locked) {
                  event.preventDefault();
                  return;
                }
                event.stopPropagation();
                drag.current = {
                  sourceId: n.section_id,
                  placement: form.placement,
                  key: treeKey,
                  scope: storageKey,
                };
                event.dataTransfer.effectAllowed = "move";
              }}
              onDragEnd={() => {
                drag.current = null;
                setDropTarget(null);
              }}
            >
              移动
            </button>
          </div>
          {hasChildren && (
            <ol id={control} hidden={!open}>
              {rows(n.section_id, depth + 1)}
            </ol>
          )}
        </li>
      );
    });
  }
  return (
    <div
      className="authoring-chapter-tree"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          drag.current = null;
          setDropTarget(null);
        }
      }}
    >
      <ol className="chapter-tree" aria-label="当前章节层级">
        {rows(null)}
      </ol>
      <form
        aria-label="章节移动预览"
        onSubmit={(event) => {
          event.preventDefault();
          void move(
            {
              sourceId: form.sourceId,
              targetId: form.targetId,
              placement: form.placement,
            },
            form.key,
            form.scope,
          );
        }}
      >
        <p>
          拖动章节的“移动”按钮到目标章节，只生成移动预览。键盘或触屏可在下方选择同样的来源、目标和位置；确认前不改稿。
        </p>
        <fieldset disabled={locked}>
          <legend>选择章节移动范围</legend>
          <label>
            移动章节
            <select
              ref={sourceSelect}
              aria-label="移动章节"
              value={form.sourceId}
              onChange={(e) => chooseSource(e.target.value)}
            >
              <option value="">选择来源章节</option>
              {nodes.map((n) => (
                <option key={n.section_id} value={n.section_id}>
                  {n.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            目标章节
            <select
              aria-label="目标章节"
              value={form.targetId}
              onChange={(e) => {
                setForm({
                  ...form,
                  targetId: e.target.value,
                  key: treeKey,
                  scope: storageKey,
                  sourceId: stale ? "" : form.sourceId,
                });
                setError("");
              }}
            >
              <option value="">选择目标章节</option>
              {nodes.map((n) => (
                <option key={n.section_id} value={n.section_id}>
                  {n.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            移动位置
            <select
              aria-label="移动位置"
              value={form.placement}
              onChange={(e) =>
                setForm({
                  ...form,
                  placement: e.target.value as TreeMoveIntent["placement"],
                })
              }
            >
              <option value="before">放到目标之前（同级）</option>
              <option value="after">放到目标之后（同级）</option>
              <option value="inside">放入目标末尾（作为子章）</option>
            </select>
          </label>
          <p>
            当前拖放与表单位置：
            {form.placement === "before"
              ? "目标之前，同级"
              : form.placement === "after"
                ? "目标之后，同级"
                : "目标内，最后一个子章"}
            。
          </p>
          <button
            type="submit"
            className="button secondary"
            disabled={stale || !form.sourceId || !form.targetId}
          >
            {busy ? "正在生成移动预览…" : "预览所选章节移动"}
          </button>
        </fieldset>
        {stale && (
          <p role="status">
            章节目录已变化，请重新选择来源和目标；旧移动范围未发送。
          </p>
        )}
        {error && <p role="alert">{error}</p>}
      </form>
    </div>
  );
}
