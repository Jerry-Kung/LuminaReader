// remark-math 默认只识别 $...$ / $$...$$ 定界符；模型常按 LaTeX 习惯输出
// \(...\) / \[...\]，其反斜杠又会被 Markdown 的 characterEscape 抢先吞掉，
// 导致公式退化成裸括号包着 TeX 源码。渲染前统一归一化为 $ / $$ 定界。
//
// 手动扫描实现：定界符是「反斜杠 + 括号/方括号」两个字符，与 \left[ 等
// 命令（反斜杠后接字母）天然区分，也规避正则字面量对反斜杠的二义性。

function findClose(source: string, open: number, openDelim: string, closeDelim: string): number {
  // 从定界符之后开始找闭合定界符；找不到返回 -1
  return source.indexOf(closeDelim, open + openDelim.length);
}

export function normalizeMathDelimiters(content: string): string {
  if (!content || !content.includes('\\')) return content;

  let result = '';
  let i = 0;

  while (i < content.length) {
    const ch = content[i];

    // 仅当出现反斜杠时才可能是定界符
    if (ch === '\\') {
      const next = content[i + 1];
      const isBlockOpen = next === '[';
      const isInlineOpen = next === '(';

      if (isBlockOpen || isInlineOpen) {
        const openDelim = isBlockOpen ? '\\[' : '\\(';
        const closeDelim = isBlockOpen ? '\\]' : '\\)';
        const close = findClose(content, i, openDelim, closeDelim);

        if (close !== -1) {
          const inner = content.slice(i + 2, close);
          result += isBlockOpen ? `$$${inner}$$` : `$${inner}$`;
          i = close + 2;
          continue;
        }
      }
    }

    result += ch;
    i += 1;
  }

  return result;
}
