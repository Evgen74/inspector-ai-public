import type { FastifyInstance } from 'fastify';
import { ApiProblem } from '../../common/problem';
import { MultipartError, parseMultipart } from './multipart';
import { MAX_PACKAGE_BYTES } from './upload-validation';

/** Envelope allowance on top of the package limit (part headers, boundaries, registry file, fields). */
export const MULTIPART_BODY_LIMIT = MAX_PACKAGE_BYTES + 64 * 1024 * 1024;

/** `multipart/form-data` is buffered and parsed into `{fields, files}` before the handler (and the OpenAPI guard). */
export function registerMultipartParser(fastify: FastifyInstance): void {
  fastify.addContentTypeParser(
    'multipart/form-data',
    { parseAs: 'buffer', bodyLimit: MULTIPART_BODY_LIMIT },
    (req, body, done) => {
      try {
        done(null, parseMultipart(body as Buffer, String(req.headers['content-type'] ?? '')));
      } catch (err) {
        if (err instanceof MultipartError) done(new ApiProblem('VALIDATION_ERROR', { summary: err.message }), undefined);
        else done(err as Error, undefined);
      }
    },
  );
}
