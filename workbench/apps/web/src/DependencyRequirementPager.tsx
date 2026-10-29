import "./dependencyRequirementPager.css";

export const DEPENDENCY_PAGE_SIZE = 20;

type Props = {
  label: string;
  count: number;
  page: number;
  disabled: boolean;
  onPage: (page: number) => void;
};

export default function DependencyRequirementPager(props: Props) {
  const pages = Math.max(1, Math.ceil(props.count / DEPENDENCY_PAGE_SIZE));
  if (pages === 1) return null;
  return (
    <nav
      className="dependency-requirement-pager"
      aria-label={`${props.label}分页`}
    >
      <p>
        共 {props.count} 条，每页 {DEPENDENCY_PAGE_SIZE} 条；第 {props.page + 1}{" "}
        / {pages} 页。
      </p>
      <div className="dependency-requirement-pager__actions">
        <button
          type="button"
          className="button secondary"
          disabled={props.disabled || props.page === 0}
          onClick={() => props.onPage(props.page - 1)}
        >
          上一页{props.label}
        </button>
        <label>
          {props.label}页码
          <select
            value={props.page}
            disabled={props.disabled}
            onChange={(event) => props.onPage(Number(event.target.value))}
          >
            {Array.from({ length: pages }, (_, page) => (
              <option key={page} value={page}>
                第 {page + 1} 页
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="button secondary"
          disabled={props.disabled || props.page + 1 >= pages}
          onClick={() => props.onPage(props.page + 1)}
        >
          下一页{props.label}
        </button>
      </div>
    </nav>
  );
}
