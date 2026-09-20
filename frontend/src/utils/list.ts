/**
 * テキストを行区切り（既定）または指定した区切りで分割し、
 * 前後の空白と空要素を取り除く。
 */
export function splitList(text: string, separator: string | RegExp = "\n"): string[] {
  return text
    .split(separator)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}
