/**
 * TS port of inspector_common.hashing (golden vectors: packages/contracts/vectors/hashing.json).
 *
 * canonicalJson: sorted keys, separators (',', ':'), UTF-8, non-ASCII kept; no NaN/Infinity.
 * inputManifestHash: sha256 over one object's manifest rows, canonical JSON per row, sorted by file_id,
 * joined with "\n".
 */
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';

export function sha256Hex(data: string | Buffer): string {
  return createHash('sha256').update(data).digest('hex');
}

export function sha256File(file: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    createReadStream(file)
      .on('error', reject)
      .on('data', (chunk) => hash.update(chunk))
      .on('end', () => resolve(hash.digest('hex')));
  });
}

function canonicalize(value: unknown): unknown {
  if (value === null || typeof value !== 'object') {
    if (typeof value === 'number' && !Number.isFinite(value)) {
      throw new TypeError('NaN/Infinity are not allowed in canonical JSON');
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalize);
  const out: Record<string, unknown> = {};
  // Python sorts str keys by code point; for BMP keys this equals the UTF-16 order used here.
  for (const key of Object.keys(value).sort()) {
    out[key] = canonicalize((value as Record<string, unknown>)[key]);
  }
  return out;
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

export function inputManifestHash(rows: ReadonlyArray<Record<string, unknown>>): string {
  // Code-unit order, like Python's sorted() on str (never locale-aware).
  const ordered = [...rows].sort((a, b) => {
    const x = String(a.file_id);
    const y = String(b.file_id);
    return x < y ? -1 : x > y ? 1 : 0;
  });
  return sha256Hex(ordered.map((row) => canonicalJson(row)).join('\n'));
}
