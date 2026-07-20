import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const markdownComponents = {
  h1: ({ node, ...props }: any) => <h1 className="text-xl font-bold text-slate-900 mt-6 mb-2 border-b border-slate-200 pb-1" {...props} />,
  h2: ({ node, ...props }: any) => <h2 className="text-lg font-semibold text-slate-900 mt-5 mb-2" {...props} />,
  h3: ({ node, ...props }: any) => <h3 className="text-base font-semibold text-slate-800 mt-4 mb-2" {...props} />,
  h4: ({ node, ...props }: any) => <h4 className="text-sm font-semibold text-slate-800 mt-3 mb-1" {...props} />,
  p: ({ node, ...props }: any) => <p className="text-sm text-slate-800 my-2 leading-relaxed break-words" {...props} />,
  ul: ({ node, ...props }: any) => <ul className="list-disc pl-5 my-2 space-y-1 text-sm text-slate-800" {...props} />,
  ol: ({ node, ...props }: any) => <ol className="list-decimal pl-5 my-2 space-y-1 text-sm text-slate-800" {...props} />,
  li: ({ node, ...props }: any) => <li className="text-sm" {...props} />,
  blockquote: ({ node, ...props }: any) => (
    <blockquote className="border-l-4 border-slate-300 bg-slate-50 pl-4 py-1 pr-2 my-2 text-slate-600 italic rounded-r" {...props} />
  ),
  pre: ({ node, ...props }: any) => (
    <pre className="bg-slate-50 border border-slate-200 rounded p-3 my-2 overflow-x-auto text-xs font-mono text-slate-800" {...props} />
  ),
  code: ({ node, inline, className, children, ...props }: any) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="bg-slate-100 text-slate-900 px-1.5 py-0.5 rounded text-xs font-mono border border-slate-200" {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className={className} {...props}>
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
    const isExternal = href?.startsWith("http://") || href?.startsWith("https://");
    return (
      <a
        href={href}
        className="text-indigo-600 hover:text-indigo-800 underline break-all"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
        {...props}
      >
        {children}
      </a>
    );
  }
};

export interface MarkdownPreviewProps {
  content: string;
}

export default function MarkdownPreview({ content }: MarkdownPreviewProps) {
  return (
    <div className="prose prose-slate max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
