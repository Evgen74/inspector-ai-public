import { ApiProblem } from '../../common/problem';

/** VALIDATION_ERROR with a Russian summary (fills the catalogue's {summary}) and one per-field error item. */
export function validationProblem(code: string, title: string, detail: string): ApiProblem {
  return new ApiProblem('VALIDATION_ERROR', { summary: detail.replace(/[.]$/, '') }, { errors: [{ code, title, detail }] });
}
