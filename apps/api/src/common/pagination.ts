/** Query parsing after OpenAPI validation (values are already known to be valid). */
import type { PageQuery } from '../api-types';

export const DEFAULT_PAGE_SIZE = 50;

export function parsePage(query: Record<string, unknown>): PageQuery {
  const page = query.page === undefined ? 1 : Number(query.page);
  const pageSize = query.page_size === undefined ? DEFAULT_PAGE_SIZE : Number(query.page_size);
  return { page, pageSize };
}

export function optionalString(value: unknown): string | undefined {
  if (Array.isArray(value)) return optionalString(value[0]);
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}
