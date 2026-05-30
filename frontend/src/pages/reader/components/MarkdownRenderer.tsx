import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export default function MarkdownRenderer({ content, className = '' }: MarkdownRendererProps) {
  return (
    <div className={`markdown-prose ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-base font-bold text-stone-800 mt-3 mb-1.5 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm font-bold text-stone-800 mt-3 mb-1.5 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-semibold text-stone-700 mt-2.5 mb-1 first:mt-0">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-xs font-semibold text-stone-700 mt-2 mb-0.5 first:mt-0">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="text-sm text-stone-700 leading-relaxed mb-2 last:mb-0">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="text-sm text-stone-700 mb-2 pl-4 space-y-0.5 list-disc">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="text-sm text-stone-700 mb-2 pl-4 space-y-0.5 list-decimal">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed">{children}</li>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-stone-800">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-stone-600">{children}</em>
          ),
          code: ({ children, className: codeClass }) => {
            const isBlock = codeClass?.startsWith('language-');
            if (isBlock) {
              return (
                <code className="block bg-stone-100 text-stone-700 text-xs p-3 rounded-md font-mono leading-relaxed overflow-x-auto">
                  {children}
                </code>
              );
            }
            return (
              <code className="bg-amber-50 text-amber-800 text-xs px-1 py-0.5 rounded font-mono border border-amber-200/60">
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="bg-stone-100 rounded-md mb-2 overflow-x-auto">{children}</pre>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-amber-300 pl-3 my-2 text-stone-500 italic">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto mb-2">
              <table className="text-xs w-full border-collapse">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-stone-100">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="border border-stone-200 px-2 py-1 text-left font-semibold text-stone-700">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-stone-200 px-2 py-1 text-stone-600">{children}</td>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="nofollow noreferrer"
              className="text-amber-700 underline underline-offset-2 hover:text-amber-800"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="border-stone-200 my-3" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}