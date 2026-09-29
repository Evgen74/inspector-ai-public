/** Pause / cancel of an upload: aborting a command stops the Python process and its pool workers (POSIX). */
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, it } from 'vitest';
import { SpawnCommandRunner } from '../src/modules/upload/command-runner';

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const venv = path.join(repoRoot, 'services', 'ml', '.venv', 'bin', 'python');
const alive = (pid: number) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};

it.skipIf(process.platform === 'win32' || !existsSync(venv))('abort stops the command with its worker processes', async () => {
  const ac = new AbortController();
  const lines: string[] = [];
  const script = [
    'import multiprocessing as mp, os, time',
    'if __name__ == "__main__":',
    '    ps = [mp.Process(target=time.sleep, args=(300,)) for _ in range(2)]',
    '    [p.start() for p in ps]',
    '    print("pids", os.getpid(), *[p.pid for p in ps], flush=True)',
    '    time.sleep(300)',
  ].join('\n');
  const done = new SpawnCommandRunner(repoRoot).python({ args: ['-c', script], signal: ac.signal }, (l) => lines.push(l));
  for (let i = 0; i < 100 && !lines.some((l) => l.startsWith('pids')); i++) await new Promise((r) => setTimeout(r, 100));
  const pids = lines.find((l) => l.startsWith('pids'))!.split(' ').slice(1).map(Number);
  expect(pids).toHaveLength(3);
  ac.abort();
  expect(await done).not.toBe(0);
  await new Promise((r) => setTimeout(r, 300));
  expect(pids.filter(alive)).toEqual([]);
}, 30_000);
