/**
 * Job queue for upload processing: RabbitMQ (queue `inspector.jobs`) when reachable, otherwise an in-process
 * queue. One job at a time either way (prefetch 1): recognition is CPU heavy. Jobs carry only the process id;
 * the state lives in ProcessStore, so a restart recovers PENDING/PARSING processes (see UploadService).
 */
import { Injectable, Logger, type OnModuleDestroy } from '@nestjs/common';

export const JOBS_QUEUE = 'inspector.jobs';

export type JobHandler = (processId: string) => Promise<void>;

interface AmqpChannelLike {
  assertQueue(queue: string, opts: { durable: boolean }): Promise<unknown>;
  prefetch(n: number): Promise<unknown>;
  consume(queue: string, cb: (msg: { content: Buffer } | null) => void): Promise<unknown>;
  sendToQueue(queue: string, content: Buffer, opts: { persistent: boolean }): boolean;
  ack(msg: unknown): void;
  nack(msg: unknown, allUpTo: boolean, requeue: boolean): void;
  close(): Promise<void>;
}

@Injectable()
export class JobQueue implements OnModuleDestroy {
  private readonly log = new Logger(JobQueue.name);
  private handler: JobHandler | null = null;
  private channel: AmqpChannelLike | null = null;
  private connection: { close(): Promise<void> } | null = null;
  private readonly local: string[] = [];
  private draining = false;
  mode: 'rabbitmq' | 'in-process' = 'in-process';

  private url: string | null = null;
  private retry: NodeJS.Timeout | null = null;
  private stopped = false;

  /** Register the worker; tries RabbitMQ (2 s), falls back silently and keeps retrying. `url === null` = never (tests). */
  async start(handler: JobHandler, url: string | null): Promise<void> {
    this.handler = handler;
    this.url = url;
    if (url) await this.connect();
  }

  private scheduleRetry(): void {
    if (this.stopped || !this.url || this.retry) return;
    this.retry = setTimeout(() => {
      this.retry = null;
      void this.connect();
    }, 15_000);
    this.retry.unref();
  }

  private async connect(): Promise<void> {
    if (!this.url || this.stopped) return;
    try {
      const amqp = await import('amqplib');
      const conn = await Promise.race([
        amqp.connect(this.url),
        new Promise<never>((_, rej) => setTimeout(() => rej(new Error('timeout 2s')), 2000)),
      ]);
      const ch = (await conn.createChannel()) as unknown as AmqpChannelLike & {
        on(event: string, cb: (e?: Error) => void): void;
      };
      await ch.assertQueue(JOBS_QUEUE, { durable: true });
      await ch.prefetch(1);
      const fallback = (why: string) => {
        if (this.channel !== ch) return;
        this.channel = null;
        this.mode = 'in-process';
        this.log.warn(`RabbitMQ недоступен (${why}); задачи выполняются в процессе API.`);
        this.scheduleRetry();
      };
      // Every emitter needs an error listener: an unhandled 'error' event would take the whole API down.
      conn.on('error', (e: Error) => fallback(e.message));
      conn.on('close', () => fallback('соединение закрыто'));
      ch.on('error', (e?: Error) => fallback(e?.message ?? 'ошибка канала'));
      ch.on('close', () => fallback('канал закрыт'));
      await ch.consume(JOBS_QUEUE, (msg) => {
        if (!msg) return;
        const id = msg.content.toString('utf8');
        void this.handle(id).finally(() => {
          try {
            ch.ack(msg); // the channel may be gone: the message is then redelivered and the run is idempotent
          } catch {
            // ignore
          }
        });
      });
      this.channel = ch;
      this.connection = conn as unknown as { close(): Promise<void> };
      this.mode = 'rabbitmq';
      this.log.log(`Очередь ${JOBS_QUEUE}: RabbitMQ.`);
    } catch (err) {
      this.log.warn(`RabbitMQ недоступен (${(err as Error).message}); задачи выполняются в процессе API.`);
      this.scheduleRetry();
    }
  }

  enqueue(processId: string): 'rabbitmq' | 'in-process' {
    if (this.channel) {
      try {
        this.channel.sendToQueue(JOBS_QUEUE, Buffer.from(processId, 'utf8'), { persistent: true });
        return 'rabbitmq';
      } catch (err) {
        this.log.warn(`Публикация в RabbitMQ не удалась (${(err as Error).message}); выполняем в процессе.`);
      }
    }
    this.local.push(processId);
    void this.drain();
    return 'in-process';
  }

  /** Resolves when the in-process queue is empty (tests). */
  async idle(): Promise<void> {
    while (this.draining || this.local.length > 0) await new Promise((r) => setTimeout(r, 10));
  }

  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;
    try {
      for (let id = this.local.shift(); id !== undefined; id = this.local.shift()) await this.handle(id);
    } finally {
      this.draining = false;
    }
  }

  private async handle(id: string): Promise<void> {
    try {
      await this.handler?.(id);
    } catch (err) {
      this.log.error(`Задача ${id} завершилась исключением: ${(err as Error).message}`);
    }
  }

  async onModuleDestroy(): Promise<void> {
    this.stopped = true;
    if (this.retry) clearTimeout(this.retry);
    try {
      await this.channel?.close();
      await this.connection?.close();
    } catch {
      // closing a dead connection is not an error
    }
    this.channel = null;
  }
}
