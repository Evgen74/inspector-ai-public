/** Spawns the Python engine (inspector-batch / inspector_registry.adhoc) and streams its output lines. */
import { type ChildProcess, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

export interface CommandSpec {
  args: string[];
  /** Extra environment (INSPECTOR_WORKERS, …). */
  env?: Record<string, string>;
  /** Abort = stop the command with every process it started (pause / cancel of an upload). */
  signal?: AbortSignal;
}

/** Stops a command and its whole process tree (the pipeline runs pools of worker processes). */
export function killTree(child: ChildProcess): void {
  if (child.pid === undefined || child.exitCode !== null) return;
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' }).on('error', () => child.kill());
    return;
  }
  const group = -child.pid; // the child leads its own process group (spawned detached)
  try {
    process.kill(group, 'SIGTERM');
  } catch {
    child.kill('SIGTERM');
  }
  // Workers that ignore SIGTERM are killed after a grace period.
  setTimeout(() => {
    try {
      process.kill(group, 'SIGKILL');
    } catch {
      /* already gone */
    }
  }, 5000).unref();
}

export abstract class CommandRunner {
  /** Runs a Python entry point; resolves with the exit code. `onLine` gets each stdout/stderr line. */
  abstract python(spec: CommandSpec, onLine: (line: string) => void): Promise<number>;
}

export class SpawnCommandRunner extends CommandRunner {
  constructor(private readonly repoRoot: string) {
    super();
  }

  private launcher(): { cmd: string; prefix: string[]; cwd: string } {
    const cwd = path.join(this.repoRoot, 'services', 'ml');
    const venvPython =
      process.platform === 'win32' ? path.join(cwd, '.venv', 'Scripts', 'python.exe') : path.join(cwd, '.venv', 'bin', 'python');
    if (existsSync(venvPython)) return { cmd: venvPython, prefix: [], cwd };
    return { cmd: process.env.INSPECTOR_UV_BIN ?? 'uv', prefix: ['run', '--locked', 'python'], cwd };
  }

  python(spec: CommandSpec, onLine: (line: string) => void): Promise<number> {
    const { cmd, prefix, cwd } = this.launcher();
    return new Promise((resolve, reject) => {
      const env: NodeJS.ProcessEnv = { ...process.env, ...spec.env, PYTHONUNBUFFERED: '1' };
      if (!env.UV_PYTHON && existsSync('/opt/homebrew/bin/python3.12')) env.UV_PYTHON = '/opt/homebrew/bin/python3.12';
      // Own process group on POSIX, so that a pause or cancel stops the worker pools too (killTree).
      const child = spawn(cmd, [...prefix, ...spec.args], {
        cwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: process.platform !== 'win32',
      });
      if (spec.signal) {
        if (spec.signal.aborted) killTree(child);
        else spec.signal.addEventListener('abort', () => killTree(child), { once: true });
      }
      let carry = '';
      const feed = (chunk: Buffer) => {
        carry += chunk.toString('utf8');
        const lines = carry.split(/\r?\n/);
        carry = lines.pop() ?? '';
        for (const l of lines) if (l.trim()) onLine(l);
      };
      child.stdout.on('data', feed);
      child.stderr.on('data', feed);
      child.on('error', reject);
      child.on('close', (code) => {
        if (carry.trim()) onLine(carry);
        resolve(code ?? 1);
      });
    });
  }
}
