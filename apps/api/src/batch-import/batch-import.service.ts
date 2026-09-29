/**
 * Import of an `inspector-batch` run directory (97 §2.14): `<run_dir>/run_manifest.json`.
 *
 * Steps: resolve the directory inside INSPECTOR_RUNS_ROOT → validate run_manifest.json against the contract
 * (run_manifest.schema.json + referential checks) → enrich files from the organizer manifest when its sha256
 * equals `inputs.manifest_sha256` → one DB transaction (runs, objects, files).
 *
 * Hidden-test integrity (97 §2.17): for TEST_HIDDEN objects only the inventory is imported; artifact paths are
 * dropped and never read. Nothing here is tuned on any object's content.
 */
import { readFileSync, realpathSync, statSync } from 'node:fs';
import path from 'node:path';
import { Inject, Injectable } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import type { BatchRunImportResultDto, ImportedObjectDto } from '../api-types';
import { APP_CONFIG, type AppConfig, organizerManifestPath } from '../config/config';
import { ContractSchemas, summarizeAjvErrors } from '../contracts/contracts';
import { sha256Hex } from '../common/hashing';
import { ApiProblem, ErrorCatalog, type ProblemItem } from '../common/problem';
import {
  BatchRunsRepository,
  FileIdConflictError,
  type ImportPlan,
  type ImportPlanFile,
  type ImportPlanObject,
} from './batch-runs.repository';
import { baseName, type ManifestRow, readJsonl, type RunManifest } from './run-manifest';

export const RUN_MANIFEST_FILE = 'run_manifest.json';
const RUN_MANIFEST_SCHEMA = 'run_manifest.schema.json';
const DOC_STAGES = new Set(['PD', 'RD', 'ID']);

interface OrganizerManifest {
  path: string;
  sha256: string;
  byFileId: Map<string, ManifestRow>;
  corpusByObject: Map<string, string>;
}

function short(digest: string): string {
  return digest.slice(0, 12);
}

@Injectable()
export class BatchImportService {
  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly schemas: ContractSchemas,
    private readonly catalog: ErrorCatalog,
    private readonly repository: BatchRunsRepository,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(BatchImportService.name);
  }

  /** Absolute, symlink-resolved run directory strictly inside the runs root. */
  resolveRunDir(runDir: string): string {
    let runsRoot: string;
    try {
      runsRoot = realpathSync(this.config.runsRoot);
    } catch {
      throw new ApiProblem('NOT_FOUND', { run_dir: runDir, runs_root: this.config.runsRoot });
    }
    const candidate = path.resolve(runsRoot, runDir);
    let resolved: string;
    try {
      resolved = realpathSync(candidate);
    } catch {
      throw new ApiProblem('NOT_FOUND', { run_dir: runDir });
    }
    if (!resolved.startsWith(runsRoot + path.sep)) {
      throw new ApiProblem('VALIDATION_ERROR', {
        summary: `run_dir должен быть каталогом внутри каталога запусков ${runsRoot}`,
      });
    }
    if (!statSync(resolved).isDirectory()) {
      throw new ApiProblem('VALIDATION_ERROR', { summary: 'run_dir должен быть каталогом запуска, а не файлом' });
    }
    return resolved;
  }

  private contractError(reason: string, errors?: ProblemItem[]): ApiProblem {
    return new ApiProblem(
      'CONTRACT_VALIDATION_FAILED',
      { artifact: RUN_MANIFEST_FILE, schema: RUN_MANIFEST_SCHEMA, reason },
      { status: 422, errors },
    );
  }

  /** Read and validate run_manifest.json: JSON Schema + checks the schema cannot express. */
  readRunManifest(runDir: string): { manifest: RunManifest; bytes: Buffer; file: string } {
    const file = path.join(runDir, RUN_MANIFEST_FILE);
    let bytes: Buffer;
    try {
      bytes = readFileSync(file);
    } catch {
      throw new ApiProblem('NOT_FOUND', { run_dir: runDir, file: RUN_MANIFEST_FILE });
    }
    let data: unknown;
    try {
      data = JSON.parse(bytes.toString('utf8'));
    } catch (err) {
      throw this.contractError(`некорректный JSON (${err instanceof Error ? err.message : String(err)})`);
    }
    const result = this.schemas.validate('run_manifest', data);
    if (!result.valid) {
      throw this.contractError(
        summarizeAjvErrors(result.errors),
        result.errors.slice(0, 50).map((e) =>
          this.catalog.item(
            'CONTRACT_VALIDATION_FAILED',
            { artifact: RUN_MANIFEST_FILE, schema: RUN_MANIFEST_SCHEMA, reason: summarizeAjvErrors([e]) },
            { pointer: e.instancePath || '/' },
          ),
        ),
      );
    }
    const manifest = data as RunManifest;
    const objectIds = new Set<string>();
    for (const o of manifest.objects) {
      if (objectIds.has(o.object_id)) throw this.contractError(`объект ${o.object_id} указан в objects[] дважды`);
      objectIds.add(o.object_id);
    }
    const fileIds = new Set<string>();
    for (const f of manifest.files) {
      if (fileIds.has(f.file_id)) throw this.contractError(`файл ${f.file_id} указан в files[] дважды`);
      fileIds.add(f.file_id);
      if (!objectIds.has(f.object_id)) {
        throw this.contractError(`файл ${f.file_id} относится к объекту ${f.object_id}, которого нет в objects[]`);
      }
    }
    return { manifest, bytes, file };
  }

  /** Organizer manifest (read-only); null when the data root is absent. */
  private readOrganizerManifest(warnings: ProblemItem[], runDir?: string, expectedSha?: string): OrganizerManifest | null {
    // Ad-hoc registry of a user upload: the run carries its own document_manifest.jsonl (inspector_registry.adhoc).
    if (runDir && expectedSha) {
      const local = path.join(runDir, 'document_manifest.jsonl');
      try {
        const raw = readFileSync(local);
        if (sha256Hex(raw) === expectedSha) {
          const rows = readJsonl<ManifestRow>(local);
          const byFileId = new Map<string, ManifestRow>();
          const corpusByObject = new Map<string, string>();
          for (const row of rows) {
            byFileId.set(row.file_id, row);
            if (row.corpus && !corpusByObject.has(row.object_id)) corpusByObject.set(row.object_id, row.corpus);
          }
          return { path: local, sha256: expectedSha, byFileId, corpusByObject };
        }
      } catch {
        // no run-local registry: the organizer manifest applies
      }
    }
    const file = organizerManifestPath(this.config.dataRoot);
    let raw: Buffer;
    try {
      raw = readFileSync(file);
    } catch {
      warnings.push(this.catalog.item('DATA_ROOT_NOT_FOUND', { path: file }));
      return null;
    }
    let rows: ManifestRow[];
    try {
      rows = readJsonl<ManifestRow>(file);
    } catch (err) {
      warnings.push(
        this.catalog.item('MANIFEST_UNREADABLE', { path: file, reason: err instanceof Error ? err.message : String(err) }),
      );
      return null;
    }
    const byFileId = new Map<string, ManifestRow>();
    const corpusByObject = new Map<string, string>();
    for (const row of rows) {
      byFileId.set(row.file_id, row);
      if (row.corpus && !corpusByObject.has(row.object_id)) corpusByObject.set(row.object_id, row.corpus);
    }
    return { path: file, sha256: sha256Hex(raw), byFileId, corpusByObject };
  }

  buildPlan(
    manifest: RunManifest,
    manifestFile: string,
    manifestBytes: Buffer,
  ): { plan: ImportPlan; objects: ImportedObjectDto[]; warnings: ProblemItem[] } {
    const warnings: ProblemItem[] = [];
    const organizer = this.readOrganizerManifest(warnings, path.dirname(manifestFile), manifest.inputs.manifest_sha256);
    let organizerTrusted = organizer !== null;
    if (organizer && organizer.sha256 !== manifest.inputs.manifest_sha256) {
      organizerTrusted = false;
      warnings.push(
        this.catalog.item('REGISTRY_HASH_MISMATCH', {
          file_name: path.basename(organizer.path),
          expected_short: short(manifest.inputs.manifest_sha256),
          actual_short: short(organizer.sha256),
        }),
      );
    }

    const hidden = new Set(manifest.objects.filter((o) => o.split === 'TEST_HIDDEN').map((o) => o.object_id));
    const storedObjects = manifest.objects.map((o) => {
      if (hidden.has(o.object_id) && o.artifacts && Object.keys(o.artifacts).length > 0) {
        warnings.push(this.catalog.item('HIDDEN_TEST_ACCESS_DENIED', { object_id: o.object_id }));
        const { artifacts: _dropped, ...rest } = o;
        return rest;
      }
      return o;
    });

    const planObjects: ImportPlanObject[] = manifest.objects.map((o) => ({
      id: o.object_id,
      name: (organizerTrusted && organizer?.corpusByObject.get(o.object_id)) || null,
      split: o.split,
      inputManifestHash: o.input_manifest_hash,
      scenario: o.scenario ?? null,
    }));

    const splitByObject = new Map(manifest.objects.map((o) => [o.object_id, o.split]));
    const planFiles: ImportPlanFile[] = manifest.files.map((f) => {
      const row = organizerTrusted ? organizer?.byFileId.get(f.file_id) : undefined;
      let enriched: ManifestRow | undefined;
      if (organizerTrusted && !row) {
        warnings.push(this.catalog.item('REGISTRY_FILE_NOT_LISTED', { file_name: f.file_id }));
      } else if (row && (row.sha256 !== f.sha256 || row.object_id !== f.object_id)) {
        warnings.push(
          this.catalog.item('REGISTRY_HASH_MISMATCH', {
            file_name: f.file_id,
            expected_short: short(row.sha256),
            actual_short: short(f.sha256),
          }),
        );
      } else {
        enriched = row;
      }
      if (f.local_status === 'MISSING_ON_DISK') {
        warnings.push(
          this.catalog.item('FILE_MISSING_ON_DISK', { file_id: f.file_id, relative_path: enriched?.relative_path ?? '—' }),
        );
      }
      const stageResolved =
        f.stage_resolved ?? (DOC_STAGES.has(f.manifest_stage) ? f.manifest_stage : null);
      return {
        id: f.file_id,
        objectId: f.object_id,
        fileHash: f.sha256,
        docStage: stageResolved,
        filePath: enriched?.relative_path ?? null,
        fileName: enriched ? baseName(enriched.relative_path) : f.file_id,
        ext: f.extension ?? enriched?.extension ?? null,
        sizeBytes: enriched?.size_bytes ?? null,
        manifestStage: f.manifest_stage,
        manifestSection: enriched?.section ?? null,
        datasetRole: enriched?.dataset_role ?? null,
        split: splitByObject.get(f.object_id) ?? null,
        duplicateGroup: enriched?.duplicate_group ?? null,
        annotationStatus: enriched?.annotation_status ?? null,
        pdfPages: f.pdf_pages ?? enriched?.pdf_pages ?? null,
        localStatus: f.local_status,
        sha256Verified: f.sha256_verified ?? null,
      };
    });

    const v = manifest.versions;
    const plan: ImportPlan = {
      run: {
        batchRunId: manifest.run_id,
        processId: null,
        mode: null,
        producer: manifest.producer,
        command: manifest.command ?? null,
        status: manifest.status,
        configHash: manifest.config_hash,
        freezeTag: manifest.freeze_tag ?? null,
        pipelineVersion: v.pipeline_version,
        matrixVersion: v.matrix_version ?? null,
        datasetVersion: v.dataset_version ?? null,
        modelVersion: v.model_version ?? null,
        engineVersions: v.engine_versions ?? null,
        versions: v,
        inputs: manifest.inputs,
        host: manifest.host ?? null,
        manifestRef: manifestFile,
        manifestSha256: sha256Hex(manifestBytes),
        manifest: { ...manifest, objects: storedObjects },
        timings: manifest.timings_s ?? null,
        importWarnings: warnings,
        objectsCount: manifest.objects.length,
        filesCount: manifest.files.length,
        startedAt: new Date(manifest.started_at),
        finishedAt: manifest.finished_at ? new Date(manifest.finished_at) : null,
      },
      objects: planObjects,
      files: planFiles,
    };
    const objects: ImportedObjectDto[] = manifest.objects.map((o, i) => ({
      object_id: o.object_id,
      name: planObjects[i]?.name ?? null,
      split: o.split,
      files_total: o.files_total,
      files_present: o.files_present,
      missing_on_disk: o.missing_on_disk,
    }));
    return { plan, objects, warnings };
  }

  async importRunDir(runDirInput: string): Promise<BatchRunImportResultDto> {
    const runDir = this.resolveRunDir(runDirInput);
    const { manifest, bytes, file } = this.readRunManifest(runDir);
    const { plan, objects, warnings } = this.buildPlan(manifest, file, bytes);
    let saved;
    try {
      saved = await this.repository.saveImport(plan);
    } catch (err) {
      if (err instanceof FileIdConflictError) {
        const [first] = err.conflicts;
        throw new ApiProblem(
          'FILE_ID_IMMUTABLE',
          { file_id: first?.file_id ?? '' },
          {
            errors: err.conflicts.slice(0, 50).map((c) =>
              this.catalog.item('FILE_ID_IMMUTABLE', { ...c }),
            ),
          },
        );
      }
      throw err;
    }
    this.logger.info(
      {
        event: 'batch_run_imported',
        batch_run_id: manifest.run_id,
        run_id: saved.run.id,
        created: saved.created,
        objects: manifest.objects.length,
        files: manifest.files.length,
        warnings: warnings.length,
      },
      'batch run imported',
    );
    return { run: saved.run, created: saved.created, objects, files_imported: manifest.files.length, warnings };
  }
}
