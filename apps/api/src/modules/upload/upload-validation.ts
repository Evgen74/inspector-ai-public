/** Intake rules for the upload endpoint (limits and formats), with catalogue error items in Russian.
 * Limits were raised from the ТЗ §9.1 values (50 МБ / 200 МБ) to 500 МБ per document and 5 ГБ per package
 * by the lead's decision (29.09) so that a full real object fits one archive. */
import type { ErrorCatalog, ProblemItem } from '../../common/problem';
import { sha256Of } from './large-buffer';
import type { MultipartFile } from './multipart';

export const MAX_FILE_BYTES = 500 * 1024 * 1024;
export const MAX_PACKAGE_BYTES = 5 * 1024 * 1024 * 1024;
export const MAX_FILES = 500;
export const DOC_EXTENSIONS = ['.pdf', '.docx', '.xml'] as const;
export const ARCHIVE_EXTENSIONS = ['.zip', '.7z', '.rar'] as const;
export const REGISTRY_EXTENSIONS = ['.csv', '.xlsx', '.json'] as const;

export function extOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i).toLowerCase();
}

/** Safe relative POSIX path of an uploaded name (no traversal, no absolute paths). */
export function safeName(name: string): string | null {
  const unified = name.normalize('NFC').replace(/\\/g, '/');
  const parts = unified.split('/').filter((p) => p !== '' && p !== '.');
  if (parts.length === 0 || parts.some((p) => p === '..' || p.includes('\0'))) return null;
  return parts.join('/');
}

type Detected = 'PDF' | 'ZIP' | '7Z' | 'RAR' | 'XML' | 'TEXT' | 'OTHER';

function detect(data: Buffer): Detected {
  const head = data.subarray(0, 8);
  if (head.subarray(0, 4).toString('latin1') === '%PDF') return 'PDF';
  if (head[0] === 0x50 && head[1] === 0x4b) return 'ZIP';
  if (head.subarray(0, 6).equals(Buffer.from([0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c]))) return '7Z';
  if (head.subarray(0, 4).toString('latin1') === 'Rar!') return 'RAR';
  const text = data.subarray(0, 512).toString('utf8').trimStart().replace(/^﻿/, '');
  if (text.startsWith('<')) return 'XML';
  return 'OTHER';
}

export interface AcceptedFile {
  name: string;
  data: Buffer;
  sha256: string;
  isArchive: boolean;
}

export interface Rejected {
  name: string;
  problem: ProblemItem;
}

export function sha256(data: Buffer): string {
  return sha256Of(data);
}

/** Per-file validation: extension, size, emptiness, content vs extension. Package-level limits are checked first. */
export function validateFiles(
  files: MultipartFile[],
  catalog: ErrorCatalog,
  maxFileBytes = MAX_FILE_BYTES,
): { accepted: AcceptedFile[]; rejected: Rejected[] } {
  const accepted: AcceptedFile[] = [];
  const rejected: Rejected[] = [];
  const names = new Set<string>();
  for (const f of files) {
    const name = safeName(f.filename) ?? '';
    const shown = f.filename || '(без имени)';
    const ext = extOf(name);
    const mb = (f.data.length / (1024 * 1024)).toFixed(1);
    const reject = (code: string, details: Record<string, unknown>) =>
      rejected.push({ name: shown, problem: catalog.item(code, { file_name: shown, ...details }, { file_name: shown }) });
    if (!name) {
      reject('UNSUPPORTED_FORMAT', { detected: '—', allowed: [...DOC_EXTENSIONS] });
      continue;
    }
    const isArchive = (ARCHIVE_EXTENSIONS as readonly string[]).includes(ext);
    if (!isArchive && !(DOC_EXTENSIONS as readonly string[]).includes(ext)) {
      reject('UNSUPPORTED_FORMAT', { detected: ext || '—', allowed: [...DOC_EXTENSIONS, ...ARCHIVE_EXTENSIONS] });
      continue;
    }
    if (f.data.length === 0) {
      reject('EMPTY_FILE', {});
      continue;
    }
    // An archive is a container: it is bounded by the package limit, its documents by the registry (500 МБ each).
    if (!isArchive && f.data.length > maxFileBytes) {
      reject('FILE_TOO_LARGE', { size_mb: mb, size_bytes: f.data.length, limit_bytes: maxFileBytes });
      continue;
    }
    const kind = detect(f.data);
    const ok =
      (ext === '.pdf' && kind === 'PDF') ||
      (ext === '.docx' && kind === 'ZIP') ||
      (ext === '.xml' && kind === 'XML') ||
      (ext === '.zip' && kind === 'ZIP') ||
      (ext === '.7z' && kind === '7Z') ||
      (ext === '.rar' && kind === 'RAR');
    if (!ok) {
      reject('CONTENT_TYPE_MISMATCH', { ext: ext.slice(1), detected: kind === 'OTHER' ? 'неизвестный формат' : kind });
      continue;
    }
    if (names.has(name)) continue; // the same relative name twice: the first one wins
    names.add(name);
    accepted.push({ name, data: f.data, sha256: sha256(f.data), isArchive });
  }
  return { accepted, rejected };
}
