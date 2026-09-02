import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Allow only http(s) and protocol-relative/in-app links; block javascript:, data:,
// vbscript:, file: etc. so LLM/tool-generated Markdown cannot execute scripts.
function safeHref(href: unknown): string | undefined {
  if (typeof href !== "string") return undefined;
  const trimmed = href.trim();
  if (!trimmed) return undefined;
  if (/^javascript:/i.test(trimmed)) return undefined;
  if (/^data:/i.test(trimmed)) return undefined;
  if (/^vbscript:/i.test(trimmed)) return undefined;
  if (/^file:/i.test(trimmed)) return undefined;
  return trimmed;
}

const lightComponents = {
  h1: ({ node, ...props }: any) => <h1 className="text-xl font-bold text-slate-900 mt-6 mb-2 border-b border-slate-200 pb-1 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  h2: ({ node, ...props }: any) => <h2 className="text-lg font-semibold text-slate-900 mt-5 mb-2 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  h3: ({ node, ...props }: any) => <h3 className="text-base font-semibold text-slate-800 mt-4 mb-2 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  h4: ({ node, ...props }: any) => <h4 className="text-sm font-semibold text-slate-800 mt-3 mb-1 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  p: ({ node, ...props }: any) => <p className="text-sm text-slate-800 my-2 leading-relaxed break-words wrap-anywhere [overflow-wrap:anywhere] [word-break:break-word]" {...props} />,
  ul: ({ node, ...props }: any) => <ul className="list-disc pl-5 my-2 space-y-1 text-sm text-slate-800 min-w-0" {...props} />,
  ol: ({ node, ...props }: any) => <ol className="list-decimal pl-5 my-2 space-y-1 text-sm text-slate-800 min-w-0" {...props} />,
  li: ({ node, ...props }: any) => <li className="text-sm wrap-anywhere [overflow-wrap:anywhere] [word-break:break-word] min-w-0" {...props} />,
  blockquote: ({ node, ...props }: any) => (
    <blockquote className="border-l-4 border-slate-300 bg-slate-50 pl-4 py-1 pr-2 my-2 text-slate-600 italic rounded-r wrap-anywhere [overflow-wrap:anywhere] min-w-0" {...props} />
  ),
  pre: ({ node, ...props }: any) => (
    <pre className="bg-slate-50 border border-slate-200 rounded p-3 my-2 overflow-x-auto text-xs font-mono text-slate-800 max-w-full min-w-0" {...props} />
  ),
  code: ({ node, inline, className, children, ...props }: any) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="bg-slate-100 text-slate-900 px-1.5 py-0.5 rounded text-xs font-mono border border-slate-200 wrap-anywhere [overflow-wrap:anywhere] [word-break:break-word] whitespace-pre-wrap" {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className={`${className ?? ""} wrap-anywhere [overflow-wrap:anywhere]`.trim()} {...props}>
        {children}
      </code>
    );
  },
  table: ({ node, ...props }: any) => (
    <div className="overflow-x-auto my-4 rounded border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm text-slate-800" {...props} />
    </div>
  ),
  thead: ({ node, ...props }: any) => <thead className="bg-slate-50 text-xs text-slate-700 uppercase font-medium" {...props} />,
  tbody: ({ node, ...props }: any) => <tbody className="divide-y divide-slate-200" {...props} />,
  tr: ({ node, ...props }: any) => <tr className="hover:bg-slate-50/50" {...props} />,
  th: ({ node, ...props }: any) => <th className="px-3 py-2 text-left font-semibold border-b border-slate-200" {...props} />,
  td: ({ node, ...props }: any) => <td className="px-3 py-2 text-slate-600" {...props} />,
  a: ({ node, href, children, ...props }: any) => {
    const safe = safeHref(href);
    if (safe === undefined) {
      return <span className="text-slate-500">{children}</span>;
    }
    const isExternal = safe.startsWith("http://") || safe.startsWith("https://");
    return (
      <a
        href={safe}
        className="text-indigo-600 hover:text-indigo-800 underline break-all"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
        {...props}
      >
        {children}
      </a>
    );
  },
};

const darkComponents = {
  h1: ({ node, ...props }: any) => <h1 className="text-xl font-bold text-slate-100 mt-6 mb-2 border-b border-slate-700 pb-1 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  h2: ({ node, ...props }: any) => <h2 className="text-lg font-semibold text-slate-100 mt-5 mb-2 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  h3: ({ node, ...props }: any) => <h3 className="text-base font-semibold text-slate-100 mt-4 mb-2 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  h4: ({ node, ...props }: any) => <h4 className="text-sm font-semibold text-slate-100 mt-3 mb-1 wrap-anywhere [overflow-wrap:anywhere]" {...props} />,
  p: ({ node, ...props }: any) => <p className="text-sm text-slate-100 my-2 leading-relaxed break-words wrap-anywhere [overflow-wrap:anywhere] [word-break:break-word]" {...props} />,
  ul: ({ node, ...props }: any) => <ul className="list-disc pl-5 my-2 space-y-1 text-sm text-slate-100 min-w-0" {...props} />,
  ol: ({ node, ...props }: any) => <ol className="list-decimal pl-5 my-2 space-y-1 text-sm text-slate-100 min-w-0" {...props} />,
  li: ({ node, ...props }: any) => <li className="text-sm text-slate-100 wrap-anywhere [overflow-wrap:anywhere] [word-break:break-word] min-w-0" {...props} />,
  blockquote: ({ node, ...props }: any) => (
    <blockquote className="border-l-4 border-slate-600 bg-slate-800/60 pl-4 py-1 pr-2 my-2 text-slate-300 italic rounded-r wrap-anywhere [overflow-wrap:anywhere] min-w-0" {...props} />
  ),
  pre: ({ node, ...props }: any) => (
    <pre className="bg-slate-800 border border-slate-700 rounded p-3 my-2 overflow-x-auto text-xs font-mono text-slate-100 max-w-full min-w-0" {...props} />
  ),
  code: ({ node, inline, className, children, ...props }: any) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="bg-slate-700 text-slate-100 px-1.5 py-0.5 rounded text-xs font-mono border border-slate-600 wrap-anywhere [overflow-wrap:anywhere] [word-break:break-word] whitespace-pre-wrap" {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className={`${className ?? ""} wrap-anywhere [overflow-wrap:anywhere]`.trim()} {...props}>
        {children}
      </code>
    );
  },
  table: ({ node, ...props }: any) => (
    <div className="overflow-x-auto my-4 rounded border border-slate-700">
      <table className="min-w-full divide-y divide-slate-700 text-sm text-slate-100" {...props} />
    </div>
  ),
  thead: ({ node, ...props }: any) => <thead className="bg-slate-800 text-xs text-slate-300 uppercase font-medium" {...props} />,
  tbody: ({ node, ...props }: any) => <tbody className="divide-y divide-slate-700" {...props} />,
  tr: ({ node, ...props }: any) => <tr className="hover:bg-slate-800/50" {...props} />,
  th: ({ node, ...props }: any) => <th className="px-3 py-2 text-left font-semibold border-b border-slate-600 text-slate-100" {...props} />,
  td: ({ node, ...props }: any) => <td className="px-3 py-2 text-slate-300" {...props} />,
  a: ({ node, href, children, ...props }: any) => {
    const safe = safeHref(href);
    if (safe === undefined) {
      return <span className="text-slate-400">{children}</span>;
    }
    const isExternal = safe.startsWith("http://") || safe.startsWith("https://");
    return (
      <a
        href={safe}
        className="text-sky-400 hover:text-sky-300 underline break-all"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
        {...props}
      >
        {children}
      </a>
    );
  },
};

export interface MarkdownPreviewProps {
  content: string;
  variant?: "light" | "dark";
}

export default function MarkdownPreview({ content, variant = "light" }: MarkdownPreviewProps) {
  const components = variant === "dark" ? darkComponents : lightComponents;
  return (
    <div className={`${variant === "dark" ? "max-w-none" : "prose prose-slate max-w-none"} min-w-0 overflow-hidden [overflow-wrap:anywhere]`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
