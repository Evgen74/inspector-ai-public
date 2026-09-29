import { useMutation } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import type { components } from '../../api/schema.gen';

export type SelftestReport = components['schemas']['SelftestReport'];

export function useRunSelftest(csrf: string | null | undefined) {
  return useMutation({
    // No body and no JSON content-type: the operation declares no requestBody (a JSON body is answered with 415).
    mutationFn: () =>
      apiFetch<SelftestReport>('/admin/selftest/run', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID(), ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
      }),
  });
}

export { apiFetch };
