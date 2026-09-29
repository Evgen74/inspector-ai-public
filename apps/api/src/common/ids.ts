/** Identifier helpers: UUID v7 (90 §3.3.2) and request-id acceptance. */
import { randomBytes } from 'node:crypto';

/** RFC 9562 UUID version 7: 48-bit Unix time in ms + 74 random bits. Sortable by creation time. */
export function uuidv7(now: number = Date.now()): string {
  const b = randomBytes(16);
  let ts = BigInt(now);
  for (let i = 5; i >= 0; i -= 1) {
    b[i] = Number(ts & 0xffn);
    ts >>= 8n;
  }
  b[6] = (b[6]! & 0x0f) | 0x70; // version 7
  b[8] = (b[8]! & 0x3f) | 0x80; // variant 10xx
  const h = b.toString('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const ACCEPTED_REQUEST_ID = /^[A-Za-z0-9._:-]{8,128}$/;

/** Reuse a well-formed client/proxy `X-Request-Id`, otherwise generate a UUID v7. */
export function pickRequestId(header: string | string[] | undefined): string {
  const value = Array.isArray(header) ? header[0] : header;
  return value && ACCEPTED_REQUEST_ID.test(value) ? value : uuidv7();
}
