/** The worker side: prepare (ad-hoc registry) → inspector-batch run → import → READY / FAILED; pause and cancel. */
import { copyFileSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ApiProblem } from '../../common/problem';
import { APP_CONFIG, type AppConfig, PACKAGE_DIR_NAME } from '../../config/config';
import { ObjectsRepository } from '../../objects/objects.repository';
import { RunImportService } from '../import/run-import.service';
import { CommandRunner } from './command-runner';
import { parseProgressLine, type ProcessFile, type ProcessRecord, ProcessStore } from './process-store';

/** Steps of `inspector-batch run` executed for an upload (no `score`: there is no answer key). */
export const BATCH_STEPS = ['inventory', 'recognize', 'layout', 'tables', 'compare', 'export'] as const;
/** The recognizer logs progress often; the record is written at most this often. */
export const PROGRESS_SAVE_INTERVAL_MS = 5000;
/** CPU etiquette: the host is shared with other jobs (the cap is `AppConfig.uploadWorkers`, INSPECTOR_UPLOAD_WORKERS). */

interface PrepareSummary {
  files: Array<{
    file_id: string;
    name: string;
    size_bytes: number;
    sha256: string;
    stage: string;
    stage_source: string;
    pdf_pages: number | null;
    from_archive: string | null;
    problems: string[];
  }>;
  notes: string[];
}

@Injectable()
export class UploadJob {
  private readonly log = new Logger(UploadJob.name);
  readonly store: ProcessStore;
  /** Processes being run by this API process (a redelivered or re-enqueued job must not run twice at once). */
  private readonly running = new Set<string>();
  /** Abort handle of each running process and why it was stopped (pause or cancel). */
  private readonly aborts = new Map<string, AbortController>();
  private readonly stops = new Map<string, 'PAUSED' | 'CANCELLED'>();

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly commands: CommandRunner,
    private readonly importer: RunImportService,
    private readonly objects: ObjectsRepository,
  ) {
    this.store = new ProcessStore(config.runsRoot);
  }

  private note(rec: ProcessRecord, message: string, level: 'info' | 'warn' | 'error' = 'info'): void {
    rec.log.push({ ts: new Date().toISOString(), level, message });
  }

  private step(rec: ProcessRecord, name: string, status: 'RUNNING' | 'DONE' | 'FAILED'): void {
    const s = rec.steps.find((x) => x.step === name);
    if (!s) return;
    const now = new Date().toISOString();
    if (status === 'RUNNING') s.started_at = now;
    else s.finished_at = now;
    s.status = status;
    if (status === 'RUNNING') rec.stage = name;
    // Stage progress belongs to one step: drop it when a step starts or ends.
    if (rec.progress) rec.progress.stage = null;
    this.store.save(rec);
  }

  async run(processId: string): Promise<void> {
    if (this.running.has(processId)) return;
    this.running.add(processId);
    this.aborts.set(processId, new AbortController());
    try {
      await this.execute(processId);
    } finally {
      this.running.delete(processId);
      this.aborts.delete(processId);
      this.stops.delete(processId);
    }
  }

  /**
   * Pause (PAUSED, resumable: recognised pages stay in the token cache) or cancel (CANCELLED, final). A queued
   * process changes at once; a running one is stopped with its whole process tree and changes when the pipeline has
   * exited (a few seconds). The import into the database is not interrupted: a stop requested then comes too late.
   */
  stop(processId: string, to: 'PAUSED' | 'CANCELLED'): ProcessRecord {
    const rec = this.store.get(processId);
    if (!rec) throw new ApiProblem('PROCESS_NOT_FOUND', {});
    const allowed = to === 'PAUSED' ? ['PENDING', 'PARSING'] : ['PENDING', 'PARSING', 'PAUSED'];
    if (!allowed.includes(rec.status)) throw new ApiProblem('PROCESS_STATE_CONFLICT', { status: rec.status });
    const abort = this.aborts.get(processId);
    if (rec.status === 'PARSING' && abort) {
      this.stops.set(processId, to);
      this.note(rec, to === 'PAUSED' ? 'Запрошена пауза: обработка останавливается.' : 'Запрошена отмена: обработка останавливается.');
      this.store.save(rec);
      abort.abort();
      return rec;
    }
    this.finishStopped(rec, to);
    this.store.save(rec);
    return rec;
  }

  /** PAUSED → PENDING; the caller puts it back into the queue. */
  resume(processId: string): ProcessRecord {
    const rec = this.store.get(processId);
    if (!rec) throw new ApiProblem('PROCESS_NOT_FOUND', {});
    if (rec.status !== 'PAUSED') throw new ApiProblem('PROCESS_STATE_CONFLICT', { status: rec.status });
    rec.status = 'PENDING';
    rec.error = null;
    rec.finished_at = null;
    this.note(rec, 'Обработка продолжена: уже распознанные страницы берутся из кэша.');
    this.store.save(rec);
    return rec;
  }

  private finishStopped(rec: ProcessRecord, to: 'PAUSED' | 'CANCELLED'): void {
    rec.status = to;
    rec.stage = null;
    if (rec.progress) rec.progress.stage = null;
    rec.finished_at = new Date().toISOString();
    for (const s of rec.steps) {
      if (s.status !== 'RUNNING') continue;
      s.status = 'PENDING';
      s.started_at = null;
    }
    this.note(
      rec,
      to === 'PAUSED'
        ? 'Обработка приостановлена. Распознанные страницы сохранены: «Продолжить» возобновит её с того же места.'
        : 'Обработка отменена.',
      'warn',
    );
  }

  private async execute(processId: string): Promise<void> {
    const rec = this.store.get(processId);
    // A paused or cancelled process left in the queue is not run.
    if (!rec || rec.status === 'READY' || rec.status === 'PAUSED' || rec.status === 'CANCELLED') return;
    rec.status = 'PARSING';
    rec.started_at = new Date().toISOString();
    rec.error = null;
    for (const s of rec.steps) {
      s.status = 'PENDING';
      s.started_at = null;
      s.finished_at = null;
    }
    this.note(rec, 'Обработка началась.');
    this.store.save(rec);
    try {
      await this.prepare(rec);
      await this.batch(rec);
      await this.importRun(rec);
      rec.status = 'READY';
      rec.stage = null;
      rec.finished_at = new Date().toISOString();
      for (const f of rec.files) if (f.status !== 'REJECTED') f.status = 'DONE';
      this.note(rec, 'Готово: протокол сформирован и доступен для верификации.');
    } catch (err) {
      const stopped = this.stops.get(processId);
      if (stopped) {
        this.finishStopped(rec, stopped);
        this.store.save(rec);
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      rec.status = 'FAILED';
      rec.progress.stage = null;
      rec.error = message;
      rec.finished_at = new Date().toISOString();
      const running = rec.steps.find((s) => s.status === 'RUNNING');
      if (running) {
        running.status = 'FAILED';
        running.finished_at = rec.finished_at;
      }
      this.note(rec, message, 'error');
      this.log.error(`process ${processId}: ${message}`);
    }
    this.store.save(rec);
  }

  private async prepare(rec: ProcessRecord): Promise<void> {
    this.step(rec, 'prepare', 'RUNNING');
    const dir = this.store.dir(rec.process_id);
    const args = [
      '-m',
      'inspector_registry.adhoc',
      'prepare',
      '--upload-dir',
      dir,
      '--object-name',
      rec.object_name,
      '--object-id',
      rec.object_id,
    ];
    if (rec.registry_file) args.push('--registry', path.join(dir, 'registry', rec.registry_file));
    const tail: string[] = [];
    const code = await this.commands.python({ args, signal: this.aborts.get(rec.process_id)?.signal }, (l) => tail.push(l));
    if (code !== 0) throw new Error(`Не удалось подготовить комплект: ${tail.slice(-3).join(' ') || `код ${code}`}`);
    const summary = JSON.parse(readFileSync(path.join(dir, 'prepare.json'), 'utf8')) as PrepareSummary;
    const rejected = rec.files.filter((f) => f.status === 'REJECTED');
    const prepared: ProcessFile[] = summary.files.map((f) => ({
      file_id: f.file_id,
      name: f.name,
      size_bytes: f.size_bytes,
      sha256: f.sha256,
      status: 'PREPARED',
      stage: f.stage,
      stage_source: f.stage_source,
      pages: f.pdf_pages,
      problems: f.problems,
      from_archive: f.from_archive,
    }));
    rec.files = [...prepared, ...rejected];
    for (const n of summary.notes) this.note(rec, n, 'warn');
    if (prepared.length === 0) throw new Error('В комплекте нет ни одного пригодного документа (PDF, DOCX, XML).');
    const pages = prepared.reduce((n, f) => n + (f.pages ?? 0), 0);
    this.note(rec, `Реестр комплекта построен: файлов ${prepared.length}, страниц PDF ${pages}.`);
    this.step(rec, 'prepare', 'DONE');
  }

  private async batch(rec: ProcessRecord): Promise<void> {
    const dir = this.store.dir(rec.process_id);
    const runId = `upload-${rec.process_id.slice(0, 8)}`;
    rec.run_id = runId;
    for (const f of rec.files) if (f.status === 'PREPARED') f.status = 'PROCESSING';
    this.store.save(rec);
    const workers = this.config.uploadWorkers;
    const args = [
      '-m',
      'inspector_batch.cli',
      '--data-root',
      path.join(dir, 'dataroot'),
      '--runs-root',
      this.config.runsRoot,
      '--run-id',
      runId,
      '--log-format',
      'console',
      'run',
      '--object',
      rec.object_id,
      '--steps',
      BATCH_STEPS.join(','),
      '--workers',
      String(workers),
    ];
    const tail: string[] = [];
    let lastProgressSave = 0;
    const signal = this.aborts.get(rec.process_id)?.signal;
    const code = await this.commands.python({ args, env: { INSPECTOR_WORKERS: String(workers) }, signal }, (line) => {
      tail.push(line);
      if (tail.length > 20) tail.shift();
      const prog = parseProgressLine(line);
      if (prog) {
        rec.progress.stage = prog;
        const now = Date.now();
        if (now - lastProgressSave >= PROGRESS_SAVE_INTERVAL_MS) {
          lastProgressSave = now;
          this.store.save(rec);
        }
        return;
      }
      const m = /pipeline\.step\.(started|finished)\b.*\bstep=(\w+)(?:.*\bexit_code=(\d+))?/.exec(line);
      if (!m) return;
      const [, kind, name, exit] = m;
      if (!name) return;
      if (kind === 'started') {
        this.step(rec, name, 'RUNNING');
        this.note(rec, `Этап «${name}» запущен.`);
      } else {
        this.step(rec, name, exit === '0' ? 'DONE' : 'FAILED');
        this.note(rec, `Этап «${name}» завершён${exit === '0' ? '' : ` с ошибкой (код ${exit})`}.`, exit === '0' ? 'info' : 'error');
      }
    });
    if (code !== 0) {
      const detail = tail.filter((l) => /ERROR|Шаг|ошибк/i.test(l)).slice(-2).join(' | ') || tail.slice(-2).join(' | ');
      throw new Error(`Обработка комплекта завершилась с ошибкой (код ${code}). ${detail}`.trim());
    }
    // The run carries its own registry so that the import can name the object and its files (see BatchImportService).
    copyFileSync(
      path.join(dir, 'dataroot', PACKAGE_DIR_NAME, 'data', 'document_manifest.jsonl'),
      path.join(this.config.runsRoot, runId, 'document_manifest.jsonl'),
    );
  }

  private async importRun(rec: ProcessRecord): Promise<void> {
    this.step(rec, 'import', 'RUNNING');
    const runDir = path.join(this.config.runsRoot, rec.run_id ?? '');
    const result = await this.importer.importRunDir(runDir);
    const obj = result.artifacts?.objects.find((o) => o.object_id === rec.object_id) ?? result.artifacts?.objects[0];
    rec.run_db_id = result.run.id;
    rec.verification_process_id = obj?.process_id ?? null;
    rec.protocol_id = obj?.protocol?.id ?? null;
    // The address typed into the upload form goes to the object card (the batch import knows only the manifest).
    if (rec.address) {
      const stored = await this.objects.setAddress(rec.object_id, rec.address);
      if (!stored) this.note(rec, 'Адрес не сохранён в карточке объекта: объект не найден после импорта.', 'warn');
    }
    if (!obj?.protocol) this.note(rec, 'Протокол не создан: в прогоне нет артефактов протокола.', 'warn');
    this.step(rec, 'import', 'DONE');
  }
}
