/**
 * Protocol versions of an object = the PROTOCOL_JSON artifacts of the imported runs that include it
 * (97 §1.4: every number in the demo is reproducible from the batch artifacts). The protocol is served as the
 * contract JSON (protocol.schema.json, validated here); DOCX/PDF are AG-04's `export` files, streamed as is.
 *
 * Hidden-test integrity (CLAUDE.md rule 4): artifacts of TEST_HIDDEN objects are never read (403).
 */
import { createReadStream, statSync } from 'node:fs';
import type { ReadStream } from 'node:fs';
import { Injectable, Optional } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import { ApiProblem, type ProblemItem, ErrorCatalog } from '../../common/problem';
import { CatalogLookup, type ObjectRecord, type RunRecord } from '../shared/lookup.repository';
import { type ArtifactKind, RunArtifacts } from '../shared/run-artifacts';
import { VerificationService } from '../verification/verification.service';
import { enrichLocationPages } from './location-geometry';

export type ProtocolFileFormat = 'json' | 'docx' | 'pdf';

/** Minimal typed view of protocol.schema.json used by the API (the full document is passed through). */
export interface ContractProtocol {
  schema_version: 1;
  protocol_no: string;
  run_id?: string | null;
  object: { object_id: string; name?: string | null };
  version: number;
  is_final: boolean;
  status: string;
  generated_at: string;
  scenario: string;
  upload_status?: { pd?: string; rd?: string; id?: string };
  versions: { pipeline_version: string; matrix_version?: string | null };
  input_manifest_hash: string;
  content_sha256?: string | null;
  header: { status_line: string };
  appendix2: {
    section3_not_checked_no_id: { count: number };
    section4_critical: { count: number; rows: Array<Record<string, unknown>> };
    section5_substantial: { count: number; rows: Array<Record<string, unknown>> };
    section6_ai_suspicions: { count: number; rows: Array<Record<string, unknown>> };
  };
  tz92_tables: Record<string, unknown>;
  evidence_cards: unknown[];
  [key: string]: unknown;
}

export interface ProtocolVersionDto {
  run_id: string;
  batch_run_id: string;
  object_id: string;
  protocol_no: string;
  version: number;
  web_version: number;
  is_latest: boolean;
  generated_at: string;
  status: string;
  is_final: boolean;
  scenario: string;
  status_line: string;
  counts: { critical: number; substantial: number; suspicions: number; not_checked_no_id: number; cards: number };
  formats: ProtocolFileFormat[];
  pipeline_version: string;
  matrix_version: string | null;
  input_manifest_hash: string;
  content_sha256: string | null;
}

export interface LoadedProtocol {
  run: RunRecord;
  protocol: ContractProtocol;
  version: ProtocolVersionDto;
}

const FORMAT_KIND: Record<ProtocolFileFormat, ArtifactKind> = {
  json: 'PROTOCOL_JSON',
  docx: 'PROTOCOL_DOCX',
  pdf: 'PROTOCOL_PDF',
};

export const FORMAT_MEDIA_TYPE: Record<ProtocolFileFormat, string> = {
  json: 'application/json',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pdf: 'application/pdf',
};

export function isHiddenSplit(split: string | null | undefined): boolean {
  return split === 'TEST_HIDDEN';
}

@Injectable()
export class ProtocolsService {
  constructor(
    private readonly lookup: CatalogLookup,
    private readonly artifacts: RunArtifacts,
    private readonly catalog: ErrorCatalog,
    private readonly logger: PinoLogger,
    @Optional() private readonly verification?: VerificationService,
  ) {
    this.logger.setContext(ProtocolsService.name);
  }

  /**
   * The real state of a version: the file's own status is the batch's «IN_VERIFICATION»; the inspector's work
   * (verification completed, protocol finalized as v2) lives in the web process and is applied here, so that the
   * list, the version selector, the dashboard and the protocol body all say the same thing.
   */
  private async withWebState(run: RunRecord, protocol: ContractProtocol, v: ProtocolVersionDto): Promise<ProtocolVersionDto> {
    if (!this.verification) return v;
    try {
      const merged = (await this.verification.decisionsOverlay(run.id, v.object_id, protocol as never)) as
        | (Partial<ContractProtocol> & { process_status?: string })
        | null;
      if (!merged) return v;
      const isFinal = merged.is_final === true;
      const status = isFinal
        ? 'PROTOCOL_FINALIZED'
        : merged.process_status === 'COMPLETED'
          ? 'VERIFICATION_COMPLETED'
          : String(merged.status ?? v.status);
      return {
        ...v,
        status,
        is_final: isFinal,
        status_line: merged.header?.status_line ?? v.status_line,
        web_version: Math.max(v.web_version, Number(merged.version ?? 1)),
      };
    } catch {
      return v;
    }
  }

  /** 404 for an unknown object, 403 for the hidden split. */
  async requireVisibleObject(objectId: string): Promise<ObjectRecord> {
    const object = await this.lookup.getObject(objectId);
    if (!object) throw new ApiProblem('NOT_FOUND', { object_id: objectId });
    if (isHiddenSplit(object.split)) throw new ApiProblem('HIDDEN_TEST_ACCESS_DENIED', { object_id: objectId });
    return object;
  }

  private toVersion(run: RunRecord, protocol: ContractProtocol): Omit<ProtocolVersionDto, 'web_version' | 'is_latest'> {
    const formats: ProtocolFileFormat[] = ['json'];
    for (const f of ['docx', 'pdf'] as const) {
      if (this.artifacts.locate(run, FORMAT_KIND[f], { objectId: protocol.object.object_id })) formats.push(f);
    }
    const a2 = protocol.appendix2;
    return {
      run_id: run.id,
      batch_run_id: run.batchRunId,
      object_id: protocol.object.object_id,
      protocol_no: protocol.protocol_no,
      version: protocol.version,
      generated_at: new Date(protocol.generated_at).toISOString(),
      status: protocol.status,
      is_final: protocol.is_final,
      scenario: protocol.scenario,
      status_line: protocol.header.status_line,
      counts: {
        critical: a2.section4_critical.count,
        substantial: a2.section5_substantial.count,
        suspicions: a2.section6_ai_suspicions.count,
        not_checked_no_id: a2.section3_not_checked_no_id.count,
        cards: protocol.evidence_cards.length,
      },
      formats,
      pipeline_version: protocol.versions.pipeline_version,
      matrix_version: protocol.versions.matrix_version ?? null,
      input_manifest_hash: protocol.input_manifest_hash,
      content_sha256: protocol.content_sha256 ?? null,
    };
  }

  /** The protocol of an object in one run (validated), or null when the run has none. */
  private readProtocol(run: RunRecord, objectId: string): ContractProtocol | null {
    const ref = this.artifacts.locate(run, 'PROTOCOL_JSON', { objectId });
    if (!ref) return null;
    const protocol = this.artifacts.readJson(
      ref.absPath,
      'protocol',
      `${run.batchRunId}/${ref.relPath}`,
    ) as ContractProtocol;
    if (protocol.object.object_id !== objectId) {
      throw new ApiProblem(
        'CONTRACT_VALIDATION_FAILED',
        {
          artifact: `${run.batchRunId}/${ref.relPath}`,
          schema: 'protocol.schema.json',
          reason: `object.object_id = ${protocol.object.object_id}, ожидался ${objectId}`,
        },
        { status: 422 },
      );
    }
    return protocol;
  }

  /**
   * Every protocol version of a visible object, newest first. A version whose artifact violates the contract
   * is left out of the list (and logged); opening it directly returns the 422.
   */
  async listVersions(objectId: string): Promise<LoadedProtocol[]> {
    const runs = await this.lookup.runsForObject(objectId);
    const loaded: Array<{ run: RunRecord; protocol: ContractProtocol }> = [];
    for (const run of runs) {
      try {
        const protocol = this.readProtocol(run, objectId);
        if (protocol) loaded.push({ run, protocol });
      } catch (err) {
        if (!(err instanceof ApiProblem)) throw err;
        this.logger.warn(
          { event: 'protocol.skipped', object_id: objectId, batch_run_id: run.batchRunId, code: err.code, details: err.details },
          'protocol artifact skipped',
        );
      }
    }
    // Ordinal in the object's history: by when our system imported the run, then by run start, then by the
    // protocol's self-reported generation time. The artifact's own generated_at is untrusted input (a fixture
    // with a future date must never shadow a real run), so it only breaks ties.
    const chronological = [...loaded].sort(
      (a, b) =>
        a.run.importedAt.getTime() - b.run.importedAt.getTime() ||
        a.run.startedAt.getTime() - b.run.startedAt.getTime() ||
        Date.parse(a.protocol.generated_at) - Date.parse(b.protocol.generated_at),
    );
    const ordinal = new Map(chronological.map((l, i) => [l.run.id, i + 1]));
    const latestId = chronological.at(-1)?.run.id;
    return Promise.all(
      chronological.reverse().map(async (l) => ({
        run: l.run,
        protocol: l.protocol,
        version: await this.withWebState(l.run, l.protocol, {
          ...this.toVersion(l.run, l.protocol),
          web_version: ordinal.get(l.run.id) ?? 1,
          is_latest: l.run.id === latestId,
        }),
      })),
    );
  }

  async latest(objectId: string): Promise<LoadedProtocol | null> {
    return (await this.listVersions(objectId))[0] ?? null;
  }

  async getProtocol(
    objectId: string,
    runId: string,
  ): Promise<{ loaded: LoadedProtocol; findingGroups: unknown[]; warnings: ProblemItem[] }> {
    await this.requireVisibleObject(objectId);
    const runs = await this.lookup.runsForObject(objectId);
    const run = runs.find((r) => r.id === runId);
    if (!run) throw new ApiProblem('NOT_FOUND', { object_id: objectId, run_id: runId });
    const protocol = this.readProtocol(run, objectId);
    if (!protocol) throw new ApiProblem('NOT_FOUND', { object_id: objectId, run_id: runId });
    const versions = await this.listVersions(objectId);
    const listed = versions.find((v) => v.run.id === run.id);
    const version: ProtocolVersionDto =
      listed?.version ??
      (await this.withWebState(run, protocol, {
        ...this.toVersion(run, protocol),
        web_version: versions.length + 1,
        is_latest: false,
      }));
    const warnings: ProblemItem[] = [];
    let findingGroups: unknown[] = [];
    const groupsRef = this.artifacts.locate(run, 'FINDING_GROUPS', { objectId });
    if (groupsRef) {
      const { rows, invalid } = this.artifacts.readJsonl(
        groupsRef.absPath,
        'finding_group',
        `${run.batchRunId}/${groupsRef.relPath}`,
      );
      findingGroups = rows;
      const findingsRef = this.artifacts.locate(run, 'FINDINGS', { objectId });
      if (findingsRef) {
        try {
          findingGroups = enrichLocationPages(rows, this.artifacts.readJsonl(findingsRef.absPath, null, `${run.batchRunId}/${findingsRef.relPath}`).rows);
        } catch (err) {
          this.logger.warn({ event: 'protocol.location_geometry_skipped', object_id: objectId, detail: String(err) }, 'location geometry not merged');
        }
      }
      for (const reason of invalid.slice(0, 20)) {
        warnings.push(
          this.catalog.item('CONTRACT_VALIDATION_FAILED', {
            artifact: groupsRef.relPath,
            schema: 'finding_group.schema.json',
            reason,
          }),
        );
      }
    }
    return { loaded: { run, protocol, version }, findingGroups, warnings };
  }

  async exportFile(
    objectId: string,
    runId: string,
    format: ProtocolFileFormat,
  ): Promise<{ stream: ReadStream; size: number; fileName: string; mediaType: string }> {
    const { loaded } = await this.getProtocol(objectId, runId);
    const ref = this.artifacts.locate(loaded.run, FORMAT_KIND[format], { objectId });
    if (!ref) throw new ApiProblem('NOT_FOUND', { object_id: objectId, run_id: runId, format });
    const safeNo = loaded.protocol.protocol_no.replace(/[^\p{L}\p{N}._-]+/gu, '_');
    return {
      stream: createReadStream(ref.absPath),
      size: statSync(ref.absPath).size,
      fileName: `Протокол_${safeNo}_v${loaded.version.web_version}.${format}`,
      mediaType: FORMAT_MEDIA_TYPE[format],
    };
  }
}
