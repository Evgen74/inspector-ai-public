/**
 * Decision-code dictionaries (05 §3.6) read from packages/contracts/enums.yaml — never defined here.
 *
 * - DecisionRejectReason (`family`, `requires`): «Отклонить» → NEGATIVE_VERIFIED;
 * - DecisionConfirmBasis: «Подтвердить» (the GOLD expert_reason_code, auto-defaulted);
 * - DecisionClarifyBasis: «Требует уточнения»;
 * - UnfinalizeReason, RevisionBasis, PlannedAction, CommentSource, InspectorStatus, DecisionType.
 *
 * Russian comment templates and suggested fixes are wording, not vocabulary: they live in ./templates.ts.
 */
import { enumCodes, type EnumDef, loadEnums } from '../../../contracts/contracts';

export interface CodeEntry {
  code: string;
  label_ru: string;
  /** DecisionRejectReason only: MODEL_ERROR, LEGIT_DEVIATION, OTHER. */
  family?: string;
  /** DecisionRejectReason only: Decision fields that become mandatory. */
  requires: string[];
}

/** Decision fields a reason code may require (Decision contract property names). */
export const REQUIRABLE_FIELDS = ['correct_file_id', 'approved_change_ref', 'na_basis', 'duplicate_of'] as const;

/** v1.0 API aliases (97 §2.6): InspectorStatus `aliases`. */
export type AliasMap = Record<string, string>;

export class DecisionCodes {
  readonly reject: CodeEntry[];
  readonly confirm: CodeEntry[];
  readonly clarify: CodeEntry[];
  readonly unfinalize: CodeEntry[];
  readonly revisionBasis: CodeEntry[];
  readonly plannedAction: string[];
  readonly commentSource: string[];
  readonly decisionTypes: string[];
  readonly inspectorStatuses: CodeEntry[];
  /** CONFIRMED → CONFIRMED_VIOLATION, REJECTED → NEGATIVE_VERIFIED. */
  readonly aliases: AliasMap;
  private readonly labels: Map<string, Map<string, string>>;
  private readonly enums: Record<string, EnumDef>;

  constructor(enums: Record<string, EnumDef>) {
    this.enums = enums;
    const entries = (name: string): CodeEntry[] => {
      const def = enums[name];
      if (!def) throw new Error(`enum ${name} is not in packages/contracts/enums.yaml`);
      return def.values.map((v) => ({
        code: v.code,
        label_ru: v.label_ru ?? v.code,
        ...(typeof v.family === 'string' ? { family: v.family } : {}),
        requires: Array.isArray(v.requires) ? (v.requires as string[]) : [],
      }));
    };
    this.reject = entries('DecisionRejectReason');
    this.confirm = entries('DecisionConfirmBasis');
    this.clarify = entries('DecisionClarifyBasis');
    this.unfinalize = entries('UnfinalizeReason');
    this.revisionBasis = entries('RevisionBasis');
    this.inspectorStatuses = entries('InspectorStatus');
    this.plannedAction = enumCodes(enums, 'PlannedAction');
    this.commentSource = enumCodes(enums, 'CommentSource');
    this.decisionTypes = enumCodes(enums, 'DecisionType');
    this.aliases = {};
    for (const v of enums.InspectorStatus?.values ?? []) {
      for (const alias of (v.aliases as string[] | undefined) ?? []) this.aliases[alias] = v.code;
    }
    for (const r of this.reject) {
      for (const f of r.requires) {
        if (!(REQUIRABLE_FIELDS as readonly string[]).includes(f)) {
          throw new Error(`DecisionRejectReason ${r.code} requires unknown field ${f}`);
        }
      }
    }
    this.labels = new Map();
  }

  static load(contractsDir: string): DecisionCodes {
    return new DecisionCodes(loadEnums(contractsDir));
  }

  has(enumName: string, code: string | null | undefined): boolean {
    if (!code) return false;
    return (this.enums[enumName]?.values ?? []).some((v) => v.code === code);
  }

  /** label_ru of a code of any enum (the code itself when unlabelled). */
  label(enumName: string, code: string | null | undefined): string {
    if (!code) return '';
    let byCode = this.labels.get(enumName);
    if (!byCode) {
      byCode = new Map((this.enums[enumName]?.values ?? []).map((v) => [v.code, v.label_ru ?? v.code]));
      this.labels.set(enumName, byCode);
    }
    return byCode.get(code) ?? code;
  }

  rejectEntry(code: string): CodeEntry | undefined {
    return this.reject.find((r) => r.code === code);
  }

  /** Normalizes the v1.0 aliases CONFIRMED / REJECTED to the canonical DecisionType. */
  normalizeDecision(value: string): string {
    return this.aliases[value] ?? value;
  }
}
