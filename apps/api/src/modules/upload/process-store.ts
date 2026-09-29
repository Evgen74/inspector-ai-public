/** File-based store of upload processes: `<runs>/uploads/<process_id>/process.json` (no DB migration needed). */
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** ProcessStatus of the upload vertical. `FAILED` is not in enums.yaml ProcessStatus yet (open issue for AG-00). */
export type UploadStatus = 'PENDING' | 'PARSING' | 'READY' | 'FAILED';

export type FileProgress = 'RECEIVED' | 'PREPARED' | 'PROCESSING' | 'DONE' | 'REJECTED';

export interface ProcessFile {
  file_id: string | null;
  name: string;
  size_bytes: number;
  sha256: string;
  status: FileProgress;
  stage: string | null;
  stage_source: string | null;
  pages: number | null;
  problems: string[];
  from_archive: string | null;
}

export interface ProcessStep {
  step: string;
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED';
  started_at: string | null;
  finished_at: string | null;
}

/** Live progress of the running pipeline step (the recognizer reports pages done / to do). */
export interface StageProgress {
  step: string;
  done: number;
  total: number;
  pages_per_min: number | null;
}

export interface LogEntry {
  ts: string;
  level: 'info' | 'warn' | 'error';
  message: string;
}

export interface ProcessRecord {
  process_id: string;
  status: UploadStatus;
  /** Current pipeline stage (prepare | inventory | recognize | layout | tables | compare | export | import). */
  stage: string | null;
  object_id: string;
  object_name: string;
  address: string | null;
  registry_file: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  queue: 'rabbitmq' | 'in-process' | null;
  progress: { steps_done: number; steps_total: number; percent: number; stage: StageProgress | null };
  steps: ProcessStep[];
  files: ProcessFile[];
  log: LogEntry[];
  error: string | null;
  run_id: string | null;
  /** runs.id (UUID) of the imported run: the protocol route parameter. */
  run_db_id: string | null;
  /** processes.id of the imported process (verification workspace). */
  verification_process_id: string | null;
  protocol_id: string | null;
  /** «Архивировать»: set by the admin action; archived processes are hidden from the list by default. */
  archived_at?: string | null;
}

export const PIPELINE_STEPS = ['prepare', 'inventory', 'recognize', 'layout', 'tables', 'compare', 'export', 'import'] as const;
/** Typical share of the wall time per step (sums to 100); recognition dominates. */
export const STEP_WEIGHTS: Record<string, number> = {
  prepare: 2,
  inventory: 3,
  recognize: 75,
  layout: 8,
  tables: 4,
  compare: 3,
  export: 2,
  import: 3,
};
const MAX_LOG = 400;

/** Weighted percent: DONE steps count fully, a RUNNING step with stage progress counts weight × done/total. */
export function weightedPercent(record: Pick<ProcessRecord, 'status' | 'steps'> & { progress?: { stage?: StageProgress | null } }): number {
  if (record.status === 'READY') return 100;
  const weightOf = (step: string): number => STEP_WEIGHTS[step] ?? 0;
  const totalWeight = record.steps.reduce((n, s) => n + weightOf(s.step), 0);
  if (totalWeight <= 0) return 0;
  const stage = record.progress?.stage ?? null;
  let acc = 0;
  for (const s of record.steps) {
    if (s.status === 'DONE') acc += weightOf(s.step);
    else if (s.status === 'RUNNING' && stage && stage.step === s.step && stage.total > 0) {
      acc += weightOf(s.step) * Math.min(1, Math.max(0, stage.done / stage.total));
    }
  }
  return Math.min(100, Math.round((acc / totalWeight) * 100));
}

/** Parses `recognize.progress | run_id=… done=1287 total=3169 pages_per_min=80.4` from a console log line. */
export function parseProgressLine(line: string): StageProgress | null {
  const m = /\b(recognize)\.progress\b\s*\|(.*)$/.exec(line);
  if (!m) return null;
  const kv: Record<string, string> = {};
  for (const pair of (m[2] ?? '').matchAll(/(\w+)=(\S+)/g)) kv[pair[1] as string] = pair[2] as string;
  const done = Number(kv.done);
  const total = Number(kv.total);
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return null;
  const rate = kv.pages_per_min === undefined ? Number.NaN : Number(kv.pages_per_min);
  return { step: m[1] as string, done, total, pages_per_min: Number.isFinite(rate) ? rate : null };
}

export class ProcessStore {
  readonly root: string;

  constructor(runsRoot: string) {
    this.root = path.join(runsRoot, 'uploads');
  }

  dir(id: string): string {
    return path.join(this.root, id);
  }

  private file(id: string): string {
    return path.join(this.dir(id), 'process.json');
  }

  static isValidId(id: string): boolean {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
  }

  create(record: ProcessRecord): void {
    mkdirSync(this.dir(record.process_id), { recursive: true });
    this.save(record);
  }

  save(record: ProcessRecord): void {
    record.updated_at = new Date().toISOString();
    if (record.log.length > MAX_LOG) record.log.splice(0, record.log.length - MAX_LOG);
    const done = record.steps.filter((s) => s.status === 'DONE').length;
    record.progress = {
      steps_done: done,
      steps_total: record.steps.length,
      percent: weightedPercent(record),
      stage: record.status === 'READY' || record.status === 'FAILED' ? null : (record.progress?.stage ?? null),
    };
    const target = this.file(record.process_id);
    const tmp = `${target}.tmp`;
    writeFileSync(tmp, `${JSON.stringify(record, null, 1)}\n`, 'utf8');
    renameSync(tmp, target);
  }

  get(id: string): ProcessRecord | null {
    if (!ProcessStore.isValidId(id)) return null;
    const f = this.file(id);
    if (!existsSync(f)) return null;
    try {
      return JSON.parse(readFileSync(f, 'utf8')) as ProcessRecord;
    } catch {
      return null;
    }
  }

  list(): ProcessRecord[] {
    if (!existsSync(this.root)) return [];
    const out: ProcessRecord[] = [];
    for (const name of readdirSync(this.root)) {
      const rec = this.get(name);
      if (rec) out.push(rec);
    }
    return out.sort((a, b) => b.created_at.localeCompare(a.created_at));
  }
}

export function newRecord(input: {
  processId: string;
  objectId: string;
  objectName: string;
  address: string | null;
  registryFile: string | null;
  files: ProcessFile[];
}): ProcessRecord {
  const now = new Date().toISOString();
  return {
    process_id: input.processId,
    status: 'PENDING',
    stage: null,
    object_id: input.objectId,
    object_name: input.objectName,
    address: input.address,
    registry_file: input.registryFile,
    created_at: now,
    updated_at: now,
    started_at: null,
    finished_at: null,
    queue: null,
    progress: { steps_done: 0, steps_total: PIPELINE_STEPS.length, percent: 0, stage: null },
    steps: PIPELINE_STEPS.map((step) => ({ step, status: 'PENDING', started_at: null, finished_at: null })),
    files: input.files,
    log: [{ ts: now, level: 'info', message: 'Комплект принят, проверка поставлена в очередь.' }],
    error: null,
    run_id: null,
    run_db_id: null,
    verification_process_id: null,
    protocol_id: null,
  };
}
