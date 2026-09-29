/**
 * Minimal multipart/form-data parser for an already buffered body (no extra dependency).
 * Fastify buffers the body (see `registerMultipartParser` in bootstrap.ts); the total size is bounded there.
 * Searches go through `indexOfFrom`: plain `Buffer#indexOf` returns wrapped offsets above 2 GiB.
 */
import { indexOfFrom } from './large-buffer';

export interface MultipartFile {
  field: string;
  filename: string;
  contentType: string;
  data: Buffer;
}

export interface MultipartBody {
  fields: Record<string, string>;
  files: MultipartFile[];
}

export class MultipartError extends Error {}

export function boundaryOf(contentType: string): string | null {
  const m = /boundary=(?:"([^"]+)"|([^;\s]+))/i.exec(contentType);
  return m ? (m[1] ?? m[2] ?? null) : null;
}

function decodeName(raw: string): string {
  // Browsers send UTF-8 bytes in the header; Node exposes them as latin1 when the header is read as binary.
  return raw;
}

function parseDisposition(header: string): { name: string; filename: string | null } {
  const name = /\bname="((?:[^"\\]|\\.)*)"/i.exec(header)?.[1] ?? '';
  const star = /\bfilename\*=UTF-8''([^;\s]+)/i.exec(header)?.[1];
  const plain = /\bfilename="((?:[^"\\]|\\.)*)"/i.exec(header)?.[1];
  let filename: string | null = null;
  if (star) {
    try {
      filename = decodeURIComponent(star);
    } catch {
      filename = star;
    }
  } else if (plain !== undefined) {
    filename = plain.replace(/\\"/g, '"');
  }
  return { name: decodeName(name), filename };
}

export function parseMultipart(body: Buffer, contentType: string): MultipartBody {
  const boundary = boundaryOf(contentType);
  if (!boundary) throw new MultipartError('В заголовке Content-Type нет boundary.');
  const delimiter = Buffer.from(`--${boundary}`);
  const out: MultipartBody = { fields: {}, files: [] };
  let pos = indexOfFrom(body, delimiter);
  if (pos < 0) throw new MultipartError('Тело запроса не похоже на multipart/form-data.');
  for (;;) {
    pos += delimiter.length;
    if (body.subarray(pos, pos + 2).toString('latin1') === '--') break;
    if (body.subarray(pos, pos + 2).toString('latin1') === '\r\n') pos += 2;
    const headerEnd = indexOfFrom(body, '\r\n\r\n', pos);
    if (headerEnd < 0) throw new MultipartError('Повреждённая часть multipart.');
    const headers = body.subarray(pos, headerEnd).toString('utf8');
    const next = indexOfFrom(body, Buffer.concat([Buffer.from('\r\n'), delimiter]), headerEnd + 4);
    if (next < 0) throw new MultipartError('Не найден конец части multipart.');
    const data = body.subarray(headerEnd + 4, next);
    const disposition = /^content-disposition:\s*(.+)$/im.exec(headers)?.[1] ?? '';
    const type = /^content-type:\s*(.+)$/im.exec(headers)?.[1]?.trim() ?? 'application/octet-stream';
    const { name, filename } = parseDisposition(disposition);
    if (filename !== null) out.files.push({ field: name, filename, contentType: type, data });
    else if (name) out.fields[name] = data.toString('utf8');
    pos = next + 2; // skip CRLF before the delimiter
  }
  return out;
}
