/**
 * Batch-run import v2 (97 §1.4, §2.14): POST /api/v1/admin/batch-runs/import.
 *
 * 1. Resolve the run directory and validate run_manifest.json (inventory import v1, BatchImportService).
 * 2. Read `artifacts.json` and, per train object, the artifacts it lists (findings, finding groups, protocol,
 *    submission full/strict/sidecar, protocol DOCX/PDF); every file is checked against the index (size, sha256)
 *    and its contract schema before anything is written. Layout, tables and other artifacts are stored as
 *    references (run_artifacts) after a size check.
 * 3. Save the inventory (runs, objects, files), then the artifacts (processes … submission_exports) in one
 *    transaction; the import is idempotent (see RunImportRepository).
 *
 * Hidden-test integrity (97 §2.17): artifacts of TEST_HIDDEN objects (run_manifest split or split_policy.json)
 * are never opened; they are dropped with HIDDEN_TEST_ARTIFACTS_DROPPED. Inspector decisions never flow back
 * into a submission: submission_exports holds the run's files as imported.
 */
import { readFileSync } from 'node:fs';
import { Inject, Injectable } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import type { BatchRunImportResultDto } from '../../api-types';
import { BatchImportService } from '../../batch-import/batch-import.service';
import type { RunManifest } from '../../batch-import/run-manifest';
import { ApiProblem, ErrorCatalog, type ProblemItem } from '../../common/problem';
import { APP_CONFIG, type AppConfig, splitPolicyPath } from '../../config/config';
import { ContractSchemas } from '../../contracts/contracts';
import { AuditService } from '../audit/audit.service';
import {
  crossCheck,
  type FindingDoc,
  type FindingGroupDoc,
  planCheck,
  planFragments,
  planGroup,
  planSuspicions,
  type ProtocolDoc,
  sha256OfJson,
  type SubmissionDoc,
} from './import-plan';
import {
  ArtifactContractError,
  type ArtifactIssue,
  type RunArtifactEntry,
  RunArtifactsReader,
  RunLayoutRules,
} from './run-artifacts';
import {
  type ArtifactRefRow,
  type ArtifactsImportPlan,
  type ObjectImportPlan,
  type ObjectImportResult,
  ProtocolFinalizedConflict,
  RunImportRepository,
} from './run-import.repository';

export interface ArtifactsImportDto {
  /** Entries of artifacts.json stored as references (hidden objects excluded). */
  artifacts_indexed: number;
  /** Entries of hidden objects that were dropped unread. */
  artifacts_dropped: number;
  objects: ObjectImportResult[];
  warnings: ProblemItem[];
}

export type BatchRunImportV2ResultDto = BatchRunImportResultDto & { artifacts: ArtifactsImportDto | null };

/** Kinds read and stored as rows; everything else in the index is kept as a reference only. */
const PARSED_KINDS = new Set([
  'FINDING_GROUPS',
  'FINDINGS',
  'PROTOCOL_JSON',
  'PROTOCOL_DOCX',
  'PROTOCOL_PDF',
  'SUBMISSION',
  'SUBMISSION_STRICT',
  'SUBMISSION_SIDECAR',
]);
const PROCESS_KINDS = new Set(['FINDING_GROUPS', 'FINDINGS', 'PROTOCOL_JSON', 'SUBMISSION']);

interface Prepared {
  plan: Omit<ArtifactsImportPlan, 'runId'>;
  warnings: ProblemItem[];
  dropped: number;
}

@Injectable()
export class RunImportService {
  private readonly layout: RunLayoutRules;

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly schemas: ContractSchemas,
    private readonly catalog: ErrorCatalog,
    private readonly inventory: BatchImportService,
    private readonly repository: RunImportRepository,
    private readonly audit: AuditService,
    private readonly logger: PinoLogger,
  ) {
    this.logger.setContext(RunImportService.name);
    this.layout = new RunLayoutRules(config.contractsDir);
  }

  private contractProblem(err: ArtifactContractError): ApiProblem {
    const [first] = err.issues;
    return new ApiProblem(
      'CONTRACT_VALIDATION_FAILED',
      { artifact: first?.artifact ?? 'artifacts.json', schema: first?.schema ?? 'run_artifacts.schema.json', reason: first?.reason ?? '' },
      {
        status: 422,
        errors: err.issues.slice(0, 50).map((i) =>
          this.catalog.item(
            'CONTRACT_VALIDATION_FAILED',
            { artifact: i.artifact, schema: i.schema, reason: i.reason },
            i.pointer ? { pointer: i.pointer } : {},
          ),
        ),
      },
    );
  }

  /** TEST_HIDDEN object ids: the run manifest's split and, when the data root is present, split_policy.json. */
  private hiddenObjects(manifest: RunManifest): Set<string> {
    const hidden = new Set(manifest.objects.filter((o) => o.split === 'TEST_HIDDEN').map((o) => o.object_id));
    try {
      const policy = JSON.parse(readFileSync(splitPolicyPath(this.config.dataRoot), 'utf8')) as { TEST_HIDDEN?: unknown };
      if (Array.isArray(policy.TEST_HIDDEN)) for (const id of policy.TEST_HIDDEN) if (typeof id === 'string') hidden.add(id);
    } catch {
      // No data root: the run manifest's split is authoritative.
    }
    return hidden;
  }

  /** Read and validate every artifact of the run (no writes). Null when the run has no artifacts.json. */
  prepare(runDir: string, manifest: RunManifest): Prepared | null {
    const reader = new RunArtifactsReader(runDir, this.schemas, this.layout);
    const index = reader.readIndex();
    if (!index) return null;
    const issues: ArtifactIssue[] = [];
    if (index.run_id !== manifest.run_id) {
      issues.push({ artifact: 'artifacts.json', schema: 'run_artifacts.schema.json', reason: `run_id ${index.run_id} ≠ run_manifest.json ${manifest.run_id}` });
    }
    const hidden = this.hiddenObjects(manifest);
    const manifestObjects = new Set(manifest.objects.map((o) => o.object_id));
    const objectOfFile = new Map(manifest.files.map((f) => [f.file_id, f.object_id]));
    const warnings: ProblemItem[] = [];
    const refs: ArtifactRefRow[] = [];
    const byObject = new Map<string, Map<string, RunArtifactEntry>>();
    const droppedObjects = new Set<string>();
    let dropped = 0;
    for (const entry of index.artifacts) {
      const objectId = entry.object_id ?? (entry.file_id ? (objectOfFile.get(entry.file_id) ?? null) : null);
      if (objectId && hidden.has(objectId)) {
        dropped += 1;
        droppedObjects.add(objectId);
        continue; // never opened
      }
      if (entry.object_id && !manifestObjects.has(entry.object_id)) {
        issues.push({ artifact: entry.path, schema: 'run_artifacts.schema.json', reason: `объекта ${entry.object_id} нет в run_manifest.json` });
        continue;
      }
      if (PARSED_KINDS.has(entry.kind) && objectId) {
        const kinds = byObject.get(objectId) ?? new Map<string, RunArtifactEntry>();
        kinds.set(entry.kind, entry);
        byObject.set(objectId, kinds);
      } else {
        try {
          reader.checkSize(entry);
        } catch (err) {
          if (err instanceof ArtifactContractError) issues.push(...err.issues);
          else throw err;
        }
      }
      refs.push({
        path: entry.path,
        kind: entry.kind,
        format: entry.format,
        schemaName: entry.schema_name ?? null,
        objectId,
        fileId: entry.file_id ?? null,
        sha256: entry.sha256,
        sizeBytes: entry.size_bytes,
        records: entry.records ?? null,
        producer: entry.producer ?? null,
        modifiedAt: entry.modified_at ? new Date(entry.modified_at) : null,
      });
    }
    for (const objectId of [...droppedObjects].sort()) {
      warnings.push(this.catalog.item('HIDDEN_TEST_ARTIFACTS_DROPPED', { object_id: objectId }));
    }

    const objects: ObjectImportPlan[] = [];
    for (const [objectId, kinds] of [...byObject.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1))) {
      if (![...kinds.keys()].some((k) => PROCESS_KINDS.has(k))) continue;
      try {
        objects.push(this.planObject(reader, manifest, objectId, kinds, warnings));
      } catch (err) {
        if (err instanceof ArtifactContractError) issues.push(...err.issues);
        else throw err;
      }
    }
    if (issues.length) throw new ArtifactContractError(issues);
    return { plan: { batchRunId: manifest.run_id, objects, artifacts: refs }, warnings, dropped };
  }

  private planObject(
    reader: RunArtifactsReader,
    manifest: RunManifest,
    objectId: string,
    kinds: Map<string, RunArtifactEntry>,
    warnings: ProblemItem[],
  ): ObjectImportPlan {
    const issues: ArtifactIssue[] = [];
    const get = (kind: string) => kinds.get(kind);
    const groups = get('FINDING_GROUPS') ? reader.readJsonl<FindingGroupDoc>(get('FINDING_GROUPS')!, 'finding_group').values : [];
    const findings = get('FINDINGS') ? reader.readJsonl<FindingDoc>(get('FINDINGS')!, 'finding').values : [];
    const protocolRead = get('PROTOCOL_JSON') ? reader.readJson<ProtocolDoc>(get('PROTOCOL_JSON')!, 'protocol') : null;
    const full = get('SUBMISSION') ? reader.readJson<SubmissionDoc>(get('SUBMISSION')!, 'submission.extended') : null;
    const strict = get('SUBMISSION_STRICT') ? reader.readJson<SubmissionDoc>(get('SUBMISSION_STRICT')!, 'submission.strict') : null;
    const sidecar = get('SUBMISSION_SIDECAR')
      ? reader.readJson<RunManifest>(get('SUBMISSION_SIDECAR')!, 'submission_sidecar')
      : null;

    const protocol = protocolRead?.value ?? null;
    const protocolObject = (protocol?.object as { object_id?: string } | undefined)?.object_id;
    if (protocol && protocolObject !== objectId) {
      issues.push({ artifact: get('PROTOCOL_JSON')!.path, schema: 'protocol.schema.json', reason: `object.object_id ${protocolObject} ≠ ${objectId}` });
    }
    for (const [doc, kind, schema] of [
      [full, 'SUBMISSION', 'submission.extended.schema.json'],
      [strict, 'SUBMISSION_STRICT', 'submission.strict.schema.json'],
    ] as const) {
      if (doc && doc.value.object_id !== objectId) {
        issues.push({ artifact: get(kind)!.path, schema, reason: `object_id ${doc.value.object_id} ≠ ${objectId}` });
      }
    }
    const sidecarObject = sidecar?.value.objects[0]?.object_id;
    if (sidecar && sidecarObject !== objectId) {
      issues.push({ artifact: get('SUBMISSION_SIDECAR')!.path, schema: 'submission_sidecar.schema.json', reason: `objects[0].object_id ${sidecarObject} ≠ ${objectId}` });
    }
    const objectFiles = new Set(manifest.files.filter((f) => f.object_id === objectId).map((f) => f.file_id));
    const cross = crossCheck(objectId, groups, findings, objectFiles);
    for (const reason of cross.errors) {
      issues.push({ artifact: get('FINDINGS')?.path ?? get('FINDING_GROUPS')?.path ?? objectId, schema: 'finding.schema.json', reason });
    }
    for (const w of cross.warnings) warnings.push(this.catalog.item(w.code, w.details));
    if (issues.length) throw new ArtifactContractError(issues);

    const protocolExports: ObjectImportPlan['protocolExports'] = [];
    if (protocolRead) {
      protocolExports.push({ format: 'json', storageKey: protocolRead.file, sha256: get('PROTOCOL_JSON')!.sha256, sizeBytes: protocolRead.bytes.length });
    }
    for (const [kind, format] of [
      ['PROTOCOL_DOCX', 'docx'],
      ['PROTOCOL_PDF', 'pdf'],
    ] as const) {
      const entry = get(kind);
      if (!entry) continue;
      const { file, bytes } = reader.readBytes(entry);
      protocolExports.push({ format, storageKey: file, sha256: entry.sha256, sizeBytes: bytes.length });
    }

    const manifestObject = manifest.objects.find((o) => o.object_id === objectId);
    const v = protocol?.versions;
    const submissions: ObjectImportPlan['submissions'] = [];
    if (full) {
      submissions.push({
        variant: 'full',
        path: get('SUBMISSION')!.path,
        sha256: get('SUBMISSION')!.sha256,
        sizeBytes: full.bytes.length,
        rowsCount: full.value.checks.length,
        content: full.value,
        sidecar: sidecar?.value ?? null,
      });
    }
    if (strict) {
      submissions.push({
        variant: 'strict',
        path: get('SUBMISSION_STRICT')!.path,
        sha256: get('SUBMISSION_STRICT')!.sha256,
        sizeBytes: strict.bytes.length,
        rowsCount: strict.value.checks.length,
        content: strict.value,
        sidecar: null,
      });
    }
    return {
      objectId,
      fileIds: [...objectFiles].sort(),
      process: {
        scenario: protocol?.scenario ?? manifestObject?.scenario ?? null,
        scenarioBase: protocol?.scenario_base ?? null,
        uploadStatus: protocol?.upload_status ?? null,
        inputManifestHash: protocol?.input_manifest_hash ?? manifestObject?.input_manifest_hash ?? null,
        matrixVersion: v?.matrix_version ?? manifest.versions.matrix_version ?? null,
        pipelineVersion: v?.pipeline_version ?? manifest.versions.pipeline_version,
      },
      protocol:
        protocol && protocolRead
          ? {
              protocolNo: protocol.protocol_no,
              status: protocol.status,
              isFinal: protocol.is_final,
              versions: protocol.versions as Record<string, unknown>,
              matrixVersion: protocol.versions.matrix_version ?? null,
              datasetVersion: protocol.versions.dataset_version ?? null,
              modelVersion: protocol.versions.model_version ?? null,
              pipelineVersion: protocol.versions.pipeline_version,
              engineVersions: (protocol.versions.engine_versions as Record<string, unknown> | undefined) ?? null,
              inputManifestHash: protocol.input_manifest_hash,
              scenario: protocol.scenario,
              scenarioBase: protocol.scenario_base ?? null,
              uploadStatus: protocol.upload_status ?? null,
              summary: protocol.appendix2.section2_summary ?? null,
              contentJson: protocol as Record<string, unknown>,
              contentSha256: sha256OfJson(protocol),
              sourcePath: get('PROTOCOL_JSON')!.path,
              sourceSha256: get('PROTOCOL_JSON')!.sha256,
              generatedAt: new Date(protocol.generated_at),
            }
          : null,
      protocolExports,
      groups: groups.map(planGroup),
      checks: findings.map(planCheck),
      fragments: planFragments(groups, findings, protocol),
      suspicions: planSuspicions(groups, findings, protocol),
      submissions,
    };
  }

  async importRunDir(runDirInput: string): Promise<BatchRunImportV2ResultDto> {
    const runDir = this.inventory.resolveRunDir(runDirInput);
    const { manifest } = this.inventory.readRunManifest(runDir);
    let prepared: Prepared | null;
    try {
      prepared = this.prepare(runDir, manifest);
    } catch (err) {
      if (err instanceof ArtifactContractError) throw this.contractProblem(err);
      throw err;
    }
    const base = await this.inventory.importRunDir(runDirInput);
    if (!prepared) return { ...base, artifacts: null };

    let results: ObjectImportResult[];
    try {
      results = await this.repository.saveArtifacts({ ...prepared.plan, runId: base.run.id });
    } catch (err) {
      if (err instanceof ProtocolFinalizedConflict) throw new ApiProblem('PROTOCOL_FINALIZED', { object_id: err.objectId, process_id: err.processId });
      throw err;
    }
    for (const r of results) {
      if (!r.protocol?.created) continue;
      await this.audit.record(
        {
          action: 'PROTOCOL_VERSION_CREATED',
          objectType: 'PROTOCOL',
          objectId: r.protocol.id,
          constructionObjectId: r.object_id,
          processId: r.process_id,
          protocolVersion: r.protocol.version,
          details: { batch_run_id: manifest.run_id, content_sha256: r.protocol.content_sha256, source: 'BATCH_IMPORT' },
        },
        { additional: true },
      );
    }
    this.logger.info(
      {
        event: 'batch_run_artifacts_imported',
        batch_run_id: manifest.run_id,
        objects: results.map((r) => ({
          object_id: r.object_id,
          checks: r.checks,
          protocol_version: r.protocol?.version ?? null,
        })),
        dropped: prepared.dropped,
      },
      'batch run artifacts imported',
    );
    return {
      ...base,
      artifacts: {
        artifacts_indexed: prepared.plan.artifacts.length,
        artifacts_dropped: prepared.dropped,
        objects: results,
        warnings: prepared.warnings,
      },
    };
  }
}
