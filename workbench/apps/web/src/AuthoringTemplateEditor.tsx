import { useState } from "react";
import type {
  AuthoringTemplateVersionView,
  AuthoringTemplateCreate,
  AuthoringTemplateVersion,
} from "./contracts";
import { useKnowledgeInput } from "./knowledgeStorage";
import { useRecordedCommand } from "./useRecordedCommand";
import { ErrorNotice } from "./components";
type Config = AuthoringTemplateVersionView["config"];
type Outline = Extract<Config, { nodes: unknown }>;
type Layout = Exclude<Config, Outline>;
export function AuthoringTemplateEditor({
  template,
  etag,
  memberId,
  disabled,
  onSaved,
}: {
  template: AuthoringTemplateVersionView;
  etag: string | null;
  memberId: string;
  disabled: boolean;
  onSaved: (value: AuthoringTemplateVersionView) => void;
}) {
  const [name, setName] = useKnowledgeInput(
    `tender:knowledge:${memberId}:template-name:${template.id}`,
    template.name + "（自用）",
  );
  const [config, setConfig] = useKnowledgeInput<Config>(
    `tender:knowledge:${memberId}:template-config:${template.id}`,
    template.config,
  );
  const cmd = useRecordedCommand(
    `authoring-template:${memberId}:${template.id}`,
  );
  const [error, setError] = useState<unknown>(null);
  async function save(append: boolean, retry = false) {
    setError(null);
    const body: AuthoringTemplateCreate | AuthoringTemplateVersion = append
      ? { base_revision: template.revision, name: name.trim(), config }
      : { name: name.trim(), kind: template.kind, config };
    const r = retry
      ? await cmd.retry<AuthoringTemplateVersionView>()
      : await cmd.run<AuthoringTemplateVersionView>(
          append
            ? `/authoring/template-families/${template.family_id}/versions`
            : "/authoring/template-families",
          body,
          append ? (etag ?? "") : "",
        );
    if (r) {
      if (r.data.kind !== template.kind) {
        setError(new Error("模板类型与此编辑入口不一致，请读取目录核对。"));
        return;
      }
      onSaved(r.data);
    }
  }
  const locked = disabled || cmd.busy || !!cmd.pending;
  return (
    <details>
      <summary>另存模板或保存企业模板新版本</summary>
      <p className="small-note">
        保存模板只建立固定版本，不会改动当前正文；还需预览并应用到本稿。内置模板保留原样。
      </p>
      <fieldset disabled={locked}>
        <legend>编辑{template.kind === "outline" ? "目录" : "版式"}模板</legend>
        <label>
          模板名称
          <input
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {"nodes" in config ? (
          <OutlineFields value={config} onChange={setConfig} />
        ) : (
          <LayoutFields value={config} onChange={setConfig} />
        )}
        <div className="review-shortcuts">
          <button
            type="button"
            className="button secondary"
            disabled={!name.trim()}
            onClick={() => void save(false)}
          >
            另存为新的{template.kind === "outline" ? "目录" : "版式"}模板
          </button>
          {!template.is_builtin && (
            <button
              type="button"
              className="button secondary"
              disabled={!name.trim() || !etag}
              onClick={() => void save(true)}
            >
              保存此企业模板的新版本
            </button>
          )}
        </div>
      </fieldset>
      <ErrorNotice error={error ?? cmd.error} />
      {cmd.conflict && (
        <p className="notice warning">
          模板已有新版本，输入已保留。请先读取模板目录，再对照新版本；不覆盖他人保存。
        </p>
      )}
      {cmd.pending && (
        <button
          type="button"
          className="button secondary"
          disabled={cmd.busy || disabled}
          onClick={() => void save(false, true)}
        >
          恢复原模板保存结果
        </button>
      )}
    </details>
  );
}
function normalize(nodes: Outline["nodes"]) {
  const counts = new Map<string | null, number>();
  return nodes.map((n) => {
    const ordinal = counts.get(n.parent_key) ?? 0;
    counts.set(n.parent_key, ordinal + 1);
    return { ...n, ordinal };
  });
}
function OutlineFields({
  value,
  onChange,
}: {
  value: Outline;
  onChange: (v: Config) => void;
}) {
  function update(key: string, p: Partial<Outline["nodes"][number]>) {
    onChange({
      ...value,
      nodes: normalize(
        value.nodes.map((n) => (n.key === key ? { ...n, ...p } : n)),
      ),
    });
  }
  function remove(key: string) {
    const removed = new Set([key]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const n of value.nodes)
        if (n.parent_key && removed.has(n.parent_key) && !removed.has(n.key)) {
          removed.add(n.key);
          changed = true;
        }
    }
    onChange({
      ...value,
      nodes: normalize(value.nodes.filter((n) => !removed.has(n.key))),
    });
  }
  function shift(key: string, direction: number) {
    const a = [...value.nodes];
    const i = a.findIndex((n) => n.key === key);
    const siblings = a
      .map((n, index) => ({ n, index }))
      .filter((x) => x.n.parent_key === a[i].parent_key);
    const p = siblings.findIndex((x) => x.n.key === key);
    const j = siblings[p + direction]?.index;
    if (j === undefined) return;
    [a[i], a[j]] = [a[j], a[i]];
    onChange({ ...value, nodes: normalize(a) });
  }
  return (
    <div className="template-outline-fields">
      {value.nodes.map((n) => (
        <fieldset key={n.key}>
          <legend>目录项 · {n.title || "未命名"}</legend>
          <label>
            目录项名称
            <input
              value={n.title}
              maxLength={200}
              onChange={(e) => update(n.key, { title: e.target.value })}
            />
          </label>
          <label>
            目录项上级
            <select
              value={n.parent_key ?? ""}
              onChange={(e) =>
                update(n.key, { parent_key: e.target.value || null })
              }
            >
              <option value="">顶层</option>
              {value.nodes
                .filter((p) => p.key !== n.key)
                .map((p) => (
                  <option value={p.key} key={p.key}>
                    {p.title}
                  </option>
                ))}
            </select>
          </label>
          <label>
            目录项类型
            <select
              value={n.node_type}
              onChange={(e) =>
                update(n.key, {
                  node_type: e.target.value as "chapter" | "appendix",
                })
              }
            >
              <option value="chapter">正文章节</option>
              <option value="appendix">附录</option>
            </select>
          </label>
          <label>
            模板编写目标
            <textarea
              value={n.goal ?? ""}
              maxLength={8000}
              onChange={(e) => update(n.key, { goal: e.target.value })}
            />
          </label>
          <label>
            模板预算页数
            <input
              type="number"
              min={1}
              max={10000}
              value={n.planned_pages ?? ""}
              onChange={(e) =>
                update(n.key, {
                  planned_pages: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
          <div className="review-shortcuts">
            <button
              type="button"
              className="text-button"
              onClick={() => shift(n.key, -1)}
            >
              向前移一项
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => shift(n.key, 1)}
            >
              向后移一项
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => remove(n.key)}
            >
              移除此模板项及子项
            </button>
          </div>
        </fieldset>
      ))}
      <button
        type="button"
        className="button secondary"
        disabled={value.nodes.length >= 500}
        onClick={() =>
          onChange({
            ...value,
            nodes: normalize([
              ...value.nodes,
              {
                key: `item_${crypto.randomUUID()}`,
                parent_key: null,
                ordinal: 0,
                title: "新增章节",
                node_type: "chapter",
              },
            ]),
          })
        }
      >
        添加模板目录项
      </button>
      <p className="small-note">
        这里只编辑模板；实际章节匹配和删除影响必须在应用预览中核对。模板预算不等于真实章页。
      </p>
    </div>
  );
}
function LayoutFields({
  value,
  onChange,
}: {
  value: Layout;
  onChange: (v: Config) => void;
}) {
  function change(p: Partial<Layout>) {
    onChange({ ...value, ...p });
  }
  return (
    <div className="template-layout-fields">
      <p className="small-note">
        A4版式。字体仅列受支持配置；实际字体及转换范围仍由每次构建核验。
      </p>
      <label>
        模板字体
        <select
          value={value.font}
          onChange={(e) => change({ font: e.target.value as Layout["font"] })}
        >
          <option>Noto Sans CJK SC</option>
          <option>Noto Serif CJK SC</option>
        </select>
      </label>
      <label>
        模板字号（磅）
        <input
          type="number"
          min={8}
          max={24}
          step={0.5}
          value={value.font_size_halfpoints / 2}
          onChange={(e) =>
            change({ font_size_halfpoints: Number(e.target.value) * 2 })
          }
        />
      </label>
      {(
        [
          "margin_top_twips",
          "margin_right_twips",
          "margin_bottom_twips",
          "margin_left_twips",
        ] as const
      ).map((field, index) => (
        <label key={field}>
          {["上", "右", "下", "左"][index]}边距（厘米）
          <input
            type="number"
            min={0.635}
            max={7.62}
            step={0.001}
            value={Number(((value[field] * 2.54) / 1440).toFixed(3))}
            onChange={(e) =>
              change({
                [field]: Math.round((Number(e.target.value) * 1440) / 2.54),
              })
            }
          />
        </label>
      ))}
      <label>
        段后间距（磅）
        <input
          type="number"
          min={0}
          max={36}
          step={0.5}
          value={value.paragraph_after_twips / 20}
          onChange={(e) =>
            change({ paragraph_after_twips: Number(e.target.value) * 20 })
          }
        />
      </label>
      {(["cover_enabled", "page_number", "toc_enabled"] as const).map(
        (field, i) => (
          <label className="checkbox-label" key={field}>
            <input
              type="checkbox"
              checked={value[field]}
              onChange={(e) => change({ [field]: e.target.checked })}
            />
            {["生成封面", "生成页脚页码", "生成目录（页码仍待实测）"][i]}
          </label>
        ),
      )}
      {(["cover_title", "header_text", "footer_text"] as const).map(
        (field, i) => (
          <label key={field}>
            {["封面标题", "页眉文字", "页脚文字"][i]}
            <input
              value={value[field]}
              maxLength={200}
              onChange={(e) => change({ [field]: e.target.value })}
            />
          </label>
        ),
      )}
      <label>
        章节编号方式
        <select
          value={value.chapter_numbering}
          onChange={(e) =>
            change({
              chapter_numbering: e.target.value as Layout["chapter_numbering"],
            })
          }
        >
          <option value="decimal">分级数字编号</option>
          <option value="none">不生成编号</option>
        </select>
      </label>
    </div>
  );
}
