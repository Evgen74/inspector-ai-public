/**
 * Buffer helpers that stay correct above 2 GiB. Node 22 breaks there: `Buffer#indexOf` returns an int32-wrapped
 * (negative) offset, `Hash#update` throws «data is too long» and `writeFileSync` rejects the length. An upload
 * package may be up to 5 GB, so the multipart parser, the checksum and the disk write go through these helpers.
 */
import { closeSync, openSync, writeSync } from 'node:fs';
import { createHash } from 'node:crypto';

const WINDOW = 512 * 1024 * 1024;
const CHUNK = 256 * 1024 * 1024;

/** `buf.indexOf(needle, from)` searched window by window (windows overlap by the needle length). */
export function indexOfFrom(buf: Buffer, needle: Buffer | string, from = 0, window = WINDOW): number {
  const n = typeof needle === 'string' ? Buffer.from(needle, 'latin1') : needle;
  if (n.length === 0) return Math.min(from, buf.length);
  for (let start = Math.max(0, from); start < buf.length; start += window) {
    const end = Math.min(buf.length, start + window + n.length - 1);
    const i = buf.subarray(start, end).indexOf(n);
    if (i >= 0) return start + i;
  }
  return -1;
}

export function sha256Of(buf: Buffer, chunk = CHUNK): string {
  const hash = createHash('sha256');
  for (let off = 0; off < buf.length; off += chunk) hash.update(buf.subarray(off, off + chunk));
  return hash.digest('hex');
}

export function writeFileLarge(target: string, buf: Buffer, chunk = CHUNK): void {
  const fd = openSync(target, 'w');
  try {
    let off = 0;
    while (off < buf.length) off += writeSync(fd, buf, off, Math.min(chunk, buf.length - off));
  } finally {
    closeSync(fd);
  }
}
