import { Link } from "react-router-dom";
import { ROUTES } from "../../constants/routes";

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

function renderSegment(item: BreadcrumbItem, isLast: boolean) {
  if (item.to) {
    return (
      <Link
        to={item.to}
        className="cursor-pointer rounded px-1 py-0.5 hover:bg-slate-100 hover:text-slate-800"
      >
        {item.label}
      </Link>
    );
  }
  if (!isLast) return <span className="px-1">{item.label}</span>;
  return (
    <span aria-current="page" className="px-1 font-semibold text-slate-700">
      {item.label}
    </span>
  );
}

/**
 * Shared breadcrumb bar for the workflow pages. The first segment always
 * links back to the workflow list; the last segment without `to` is the
 * current page.
 */
export function WorkflowBreadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav
      aria-label="パンくず"
      className="flex flex-wrap items-center gap-1 border-b border-slate-200 bg-white px-4 py-2 text-xs text-slate-500"
    >
      <Link
        to={ROUTES.WORKFLOWS}
        className="cursor-pointer rounded px-1 py-0.5 hover:bg-slate-100 hover:text-slate-800"
      >
        ← ワークフロー一覧
      </Link>
      {items.map((item, index) => (
        <span key={item.to ?? item.label} className="flex items-center gap-1">
          <span aria-hidden="true">/</span>
          {renderSegment(item, index === items.length - 1)}
        </span>
      ))}
    </nav>
  );
}
