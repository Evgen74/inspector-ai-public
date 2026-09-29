import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { indexOfFrom, sha256Of, writeFileLarge } from '../src/modules/upload/large-buffer';
import { parseMultipart } from '../src/modules/upload/multipart';

// Node 22 breaks above 2 GiB (wrapped indexOf offsets, «data is too long», write length range): the helpers work in
// windows/chunks. Tiny windows here exercise every boundary without allocating gigabytes.
describe('large-buffer helpers', () => {
  const buf = Buffer.from('aaaa--XYZbbbb--XYZcccc');

  it('indexOfFrom finds needles across window boundaries, like Buffer#indexOf', () => {
    for (const window of [1, 2, 3, 5, 7, 64]) {
      for (let from = 0; from <= buf.length; from += 1) {
        expect(indexOfFrom(buf, '--XYZ', from, window)).toBe(buf.indexOf('--XYZ', from));
      }
      expect(indexOfFrom(buf, 'nope', 0, window)).toBe(-1);
    }
  });

  it('sha256Of and writeFileLarge give the same bytes as one-shot calls', () => {
    const data = Buffer.from(Array.from({ length: 1000 }, (_, i) => i % 251));
    expect(sha256Of(data, 7)).toBe(createHash('sha256').update(data).digest('hex'));
    const dir = mkdtempSync(path.join(tmpdir(), 'large-buffer-'));
    try {
      const target = path.join(dir, 'out.bin');
      writeFileLarge(target, data, 13);
      expect(readFileSync(target).equals(data)).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('parseMultipart still splits parts', () => {
    const body = Buffer.from('--B\r\nContent-Disposition: form-data; name="object_name"\r\n\r\nПолярная\r\n--B\r\nContent-Disposition: form-data; name="files"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.7 x\r\n--B--\r\n');
    const out = parseMultipart(body, 'multipart/form-data; boundary=B');
    expect(out.fields.object_name).toBe('Полярная');
    expect(out.files.map((f) => [f.filename, f.data.toString()])).toEqual([['a.pdf', '%PDF-1.7 x']]);
  });
});
