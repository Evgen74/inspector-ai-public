import { Controller, Get, Optional, Param, Query, Res } from '@nestjs/common';
import type { FastifyReply } from 'fastify';
import { ApiProblem, type ProblemItem } from '../../common/problem';
import { VerificationService } from '../verification/verification.service';
import { type ProtocolFileFormat, type ProtocolVersionDto, ProtocolsService } from './protocols.service';

export interface ProtocolVersionListDto {
  object_id: string;
  items: ProtocolVersionDto[];
}

export interface ProtocolViewDto {
  version: ProtocolVersionDto;
  protocol: unknown;
  finding_groups: unknown[];
  warnings: ProblemItem[];
}

const TRANSLIT: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm',
  н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'shch',
  ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
};

/** Readable ASCII form of a Russian file name («Протокол_…» → «Protokol_…»); other characters become «_». */
export function transliterate(text: string): string {
  let out = '';
  for (const ch of text) {
    const lower = ch.toLowerCase();
    const t = TRANSLIT[lower];
    if (t === undefined) {
      out += /[\x20-\x7e]/.test(ch) ? ch : '_';
    } else {
      out += ch === lower ? t : t.charAt(0).toUpperCase() + t.slice(1);
    }
  }
  return out.replace(/["\\]/g, '_');
}

/** RFC 6266 / RFC 5987: readable ASCII fallback plus the UTF-8 file name (`filename*`). */
export function contentDisposition(fileName: string): string {
  const star = encodeURIComponent(fileName).replace(/['()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
  return `attachment; filename="${transliterate(fileName)}"; filename*=UTF-8''${star}`;
}

@Controller('objects/:object_id/protocols')
export class ProtocolsController {
  constructor(
    private readonly protocols: ProtocolsService,
    @Optional() private readonly verification?: VerificationService,
  ) {}

  @Get()
  async listObjectProtocols(@Param('object_id') objectId: string): Promise<ProtocolVersionListDto> {
    await this.protocols.requireVisibleObject(objectId);
    const versions = await this.protocols.listVersions(objectId);
    return { object_id: objectId, items: versions.map((v) => v.version) };
  }

  @Get(':run_id')
  async getObjectProtocol(
    @Param('object_id') objectId: string,
    @Param('run_id') runId: string,
  ): Promise<ProtocolViewDto> {
    const { loaded, findingGroups, warnings } = await this.protocols.getProtocol(objectId, runId);
    // Show the inspector's decisions of the same process (the verification workspace is their source of truth).
    let protocol: unknown = loaded.protocol;
    try {
      const merged = await this.verification?.decisionsOverlay(loaded.run.id, objectId, loaded.protocol as never);
      if (merged) protocol = merged;
    } catch {
      // The file-based protocol stays authoritative when the decisions cannot be read.
    }
    // Groups with mixed decisions travel in the protocol's free-form `ext` (the response schema has no other room):
    // finding_group_id → confirmed / total; the web shows «Подтверждено частично: N из M».
    try {
      const progress = (await this.verification?.partialProgress(loaded.run.id, objectId)) ?? {};
      if (Object.keys(progress).length > 0) {
        const doc = protocol as { ext?: Record<string, unknown> };
        protocol = { ...doc, ext: { ...(doc.ext ?? {}), decision_progress: progress } };
      }
    } catch {
      // progress is a display hint only
    }
    return { version: loaded.version, protocol, finding_groups: findingGroups, warnings };
  }

  @Get(':run_id/export')
  async exportObjectProtocol(
    @Param('object_id') objectId: string,
    @Param('run_id') runId: string,
    @Query() query: Record<string, unknown>,
    @Res() reply: FastifyReply,
  ): Promise<void> {
    const format = String(query.format) as ProtocolFileFormat;
    if (!['json', 'docx', 'pdf'].includes(format)) throw new ApiProblem('EXPORT_FORMAT_UNSUPPORTED', { format });
    const file = await this.protocols.exportFile(objectId, runId, format);
    await reply
      .header('Content-Type', file.mediaType)
      .header('Content-Length', String(file.size))
      .header('Content-Disposition', contentDisposition(file.fileName))
      .header('Cache-Control', 'private, max-age=60')
      .send(file.stream);
  }
}
