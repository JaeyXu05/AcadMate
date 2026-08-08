export function markdownExportFilename(title: string, options: { report?: boolean } = {}): string {
  const normalized = title
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '');
  const baseName = normalized || 'paper';
  return `${baseName}${options.report ? '-report' : ''}.md`;
}

export function downloadMarkdown(title: string, content: string, options: { report?: boolean } = {}): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = markdownExportFilename(title, options);
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
