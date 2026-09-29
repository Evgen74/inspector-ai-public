/** Reachability probes (module 11) and the job-queue mode with its automatic fallback. */
import net from 'node:net';

export interface ProbeResult {
  up: boolean;
  latency_ms: number;
  detail: string | null;
}

/** TCP connect; optionally send `hello` and require `expect` in the first reply. */
export function probeTcp(host: string, port: number, opts: { timeoutMs?: number; hello?: string; expect?: string } = {}): Promise<ProbeResult> {
  const timeoutMs = opts.timeoutMs ?? 1500;
  const started = performance.now();
  return new Promise((resolve) => {
    let done = false;
    const finish = (up: boolean, detail: string | null) => {
      if (done) return;
      done = true;
      socket.destroy();
      resolve({ up, latency_ms: Math.round(performance.now() - started), detail });
    };
    const socket = net.connect({ host, port });
    socket.setTimeout(timeoutMs, () => finish(false, 'таймаут'));
    socket.on('error', (e: NodeJS.ErrnoException) => finish(false, e.code ?? e.message));
    socket.on('connect', () => {
      if (opts.hello === undefined) return finish(true, null);
      socket.write(opts.hello);
    });
    socket.on('data', (d) => {
      const text = d.toString('latin1');
      if (opts.expect === undefined || text.includes(opts.expect)) finish(true, null);
      else finish(false, 'неожиданный ответ');
    });
  });
}

export function parseHostPort(url: string, defaultPort: number): { host: string; port: number } {
  try {
    const u = new URL(url);
    return { host: u.hostname, port: u.port ? Number(u.port) : defaultPort };
  } catch {
    return { host: '127.0.0.1', port: defaultPort };
  }
}

export function probeRedis(redisUrl: string): Promise<ProbeResult> {
  const { host, port } = parseHostPort(redisUrl, 6379);
  return probeTcp(host, port, { hello: 'PING\r\n', expect: 'PONG' });
}

export const DEFAULT_RABBITMQ_URL = 'amqp://127.0.0.1:5672';

export function rabbitUrl(env: NodeJS.ProcessEnv = process.env): string {
  return env.INSPECTOR_RABBITMQ_URL || env.INSPECTOR_AMQP_URL || DEFAULT_RABBITMQ_URL;
}

/** AMQP 0-9-1 handshake: the broker answers a wrong protocol header with its own header «AMQP». */
export function probeRabbit(url: string = rabbitUrl()): Promise<ProbeResult> {
  const { host, port } = parseHostPort(url.replace(/^amqps?:/, 'http:'), 5672);
  return probeTcp(host, port, { hello: 'AMQP\x00\x00\x09\x01', expect: 'AMQP' });
}

export async function probeHttp(url: string, timeoutMs = 1500): Promise<ProbeResult> {
  const started = performance.now();
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    return { up: res.status < 500, latency_ms: Math.round(performance.now() - started), detail: `HTTP ${res.status}` };
  } catch (e) {
    const err = e as { cause?: { code?: string }; name?: string };
    return { up: false, latency_ms: Math.round(performance.now() - started), detail: err.cause?.code ?? err.name ?? 'нет ответа' };
  }
}

export type QueueMode = 'rabbitmq' | 'in-process';

/**
 * How background jobs run right now: through RabbitMQ when the broker answers, otherwise in-process (a
 * DB-polling worker / direct call). The product works either way; callers never fail because of the broker.
 */
export async function detectQueueMode(url: string = rabbitUrl()): Promise<{ mode: QueueMode; probe: ProbeResult }> {
  const probe = await probeRabbit(url).catch(
    (): ProbeResult => ({ up: false, latency_ms: 0, detail: 'ошибка проверки' }),
  );
  return { mode: probe.up ? 'rabbitmq' : 'in-process', probe };
}
