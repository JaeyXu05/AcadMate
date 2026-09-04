import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

export interface PresentationInput {
  title: string;
  template: string;
  slideCount: number;
  markdown: string;
  evidenceRefs: string[];
  visualData?: Record<string, unknown>;
}

const builder = path.join(process.cwd(), 'server', 'services', 'ppt_builder.py');

export async function buildPresentation(input: PresentationInput, outputPath: string): Promise<void> {
  await mkdir(path.dirname(outputPath), { recursive: true });
  const configured = process.env.PAPER_CLAW_PYTHON?.trim();
  const windowsPython = process.env.USERPROFILE
    ? path.join(process.env.USERPROFILE, 'AppData', 'Local', 'Microsoft', 'WindowsApps', 'python.exe')
    : 'python';
  const commands = configured
    ? [configured]
    : [
        'python',
        windowsPython,
        'python3',
      ];
  let lastError: Error | null = null;
  for (const command of commands) {
    try {
      await runBuilder(command, input, outputPath);
      return;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  throw lastError || new Error('没有可用的 Python PPT 渲染环境');
}

function runBuilder(command: string, input: PresentationInput, outputPath: string): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const child = spawn(command, [builder, outputPath], { windowsHide: true });
    let stderr = '';
    let settled = false;
    const fail = (error: Error) => { if (!settled) { settled = true; reject(error); } };
    child.stderr.on('data', (chunk) => { stderr += String(chunk); });
    child.on('error', (error) => fail(error));
    child.on('close', (code) => {
      if (settled) return;
      if (code === 0) { settled = true; resolve(); }
      else fail(new Error(stderr.trim().slice(-1000) || `PPT 渲染进程退出（${code ?? 'unknown'}）`));
    });
    child.stdin.write(JSON.stringify(input));
    child.stdin.end();
  });
}
