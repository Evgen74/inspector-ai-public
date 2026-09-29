/**
 * The three inspector actions (ТЗ §9.3 п.2) with the click budget of 05 §3.17.4: «Подтвердить нарушение» →
 * «Сохранить» (2 clicks; C, Enter; Shift+C at once), «Отклонить» → reason chip → «Сохранить» (3; R, 1–9, Enter),
 * «Требует уточнения» → basis chip → «Сохранить» (3; U, 1–8, Enter). Comments are prefilled from the server's
 * templates (comment_source TEMPLATE / EDITED / MANUAL). A rejection needs only the reason code: its comment is
 * optional and starts empty (the template is only a placeholder).
 */
import { useEffect, useImperativeHandle, useMemo, useState, forwardRef } from 'react';
import { Alert, Button, Flex, Input, Select, Space, Tag, Tooltip, Typography } from 'antd';
import { CheckOutlined, CloseOutlined, QuestionOutlined } from '@ant-design/icons';
import type { DecisionCodes, DecisionRequest, EvidenceCardView, QueueItem } from './types';

export type Panel = 'confirm' | 'reject' | 'clarify' | null;
export type DecisionDraft = Omit<DecisionRequest, 'seen_fingerprint' | 'client_metrics'>;

export interface DecisionPanelHandle {
  submit(): void;
  pickDigit(d: number): void;
}

interface Props {
  card: EvidenceCardView;
  codes: DecisionCodes;
  queue: QueueItem[];
  panel: Panel;
  setPanel(p: Panel): void;
  canDecide: boolean;
  disabledReason: string | null;
  busy: boolean;
  onSubmit(req: DecisionDraft): void;
}

function commentSource(comment: string, template: string): 'TEMPLATE' | 'EDITED' | 'MANUAL' {
  if (!template) return 'MANUAL';
  return comment.trim() === template.trim() ? 'TEMPLATE' : 'EDITED';
}

export const DecisionPanel = forwardRef<DecisionPanelHandle, Props>(function DecisionPanel(
  { card, codes, panel, setPanel, canDecide, disabledReason, busy, onSubmit },
  ref,
) {
  const [code, setCode] = useState<string | null>(null);
  const [basis, setBasis] = useState(card.prefill.confirm_basis_code);
  const [comment, setComment] = useState('');
  const [edited, setEdited] = useState(false);
  const [plannedAction, setPlannedAction] = useState<string | null>(null);
  const [justification, setJustification] = useState('');

  // A new card or another action: start from the templates again.
  useEffect(() => {
    setCode(null);
    setEdited(false);
    setPlannedAction(null);
    setJustification('');
    setBasis(card.prefill.confirm_basis_code);
    setComment(panel === 'confirm' ? card.prefill.confirm_comment : '');
  }, [card.finding_id, card.row_version, panel, card.prefill.confirm_basis_code, card.prefill.confirm_comment]);

  const template = panel === 'confirm' ? card.prefill.confirm_comment : panel === 'reject' ? (code ? card.prefill.reject_comments[code] ?? '' : '') : code ? card.prefill.clarify_comments[code] ?? '' : '';
  const rejectEntry = panel === 'reject' && code ? codes.reject.find((r) => r.code === code) : undefined;
  const needsJustification = panel === 'confirm' && card.approved_change_ref.toUpperCase() !== 'NONE';

  const pick = (c: string) => {
    setCode(c);
    if (!edited && panel !== 'reject') setComment(card.prefill.clarify_comments[c] ?? '');
  };

  const problem = useMemo((): string | null => {
    if (!canDecide) return disabledReason ?? 'Решение недоступно';
    if (!panel) return 'Выберите действие';
    if ((panel === 'reject' || panel === 'clarify') && !code) return panel === 'reject' ? 'Выберите код причины (1–9)' : 'Выберите основание (1–8)';
    if (panel !== 'reject' && !comment.trim()) return 'Нужен комментарий';
    if (needsJustification && !justification.trim()) return 'Обоснуйте подтверждение при согласованном изменении';
    return null;
  }, [canDecide, disabledReason, panel, code, comment, needsJustification, justification]);

  const submit = () => {
    if (problem || busy || !panel) return;
    const source = commentSource(comment, template);
    if (panel === 'confirm') {
      onSubmit({
        decision: 'CONFIRMED_VIOLATION',
        basis_code: basis,
        comment: comment.trim(),
        comment_source: source,
        planned_action: plannedAction,
        justification: needsJustification ? justification.trim() : null,
      });
    } else if (panel === 'reject') {
      onSubmit({
        decision: 'NEGATIVE_VERIFIED',
        reason_code: code,
        comment: comment.trim() || null,
        comment_source: comment.trim() ? source : null,
      });
    } else {
      onSubmit({ decision: 'CLARIFICATION_REQUIRED', clarify_code: code, comment: comment.trim(), comment_source: source });
    }
  };

  useImperativeHandle(ref, () => ({
    submit,
    pickDigit: (d: number) => {
      const list = panel === 'reject' ? codes.reject : panel === 'clarify' ? codes.clarify : [];
      const item = list[d - 1];
      if (item) pick(item.code);
    },
  }));

  const action = (p: Exclude<Panel, null>, label: string, key: string, icon: React.ReactNode, danger = false) => (
    <Tooltip title={`Клавиша ${key}`}>
      <Button
        type={panel === p ? 'primary' : 'default'}
        danger={danger}
        icon={icon}
        disabled={!canDecide}
        onClick={() => setPanel(panel === p ? null : p)}
        data-action={p}
      >
        {label}
      </Button>
    </Tooltip>
  );

  const chips = (list: Array<{ code: string; label_ru: string }>) => (
    <Flex wrap gap={4} role="listbox" aria-label={panel === 'reject' ? 'Код причины' : 'Основание'}>
      {list.map((c, i) => (
        <span key={c.code} role="option" aria-selected={code === c.code} data-code={c.code}>
          <Tag.CheckableTag checked={code === c.code} onChange={() => pick(c.code)} style={{ fontSize: 12, border: '1px solid #d9d9d9', marginInlineEnd: 0 }}>
            {i < 9 ? <b>{i + 1} </b> : null}
            {c.label_ru}
          </Tag.CheckableTag>
        </span>
      ))}
    </Flex>
  );

  return (
    <Flex vertical gap={8} data-testid="decision-panel">
      <Space wrap>
        {action('confirm', 'Подтвердить нарушение', 'C', <CheckOutlined />, true)}
        {action('reject', 'Отклонить', 'R', <CloseOutlined />)}
        {action('clarify', 'Требует уточнения', 'U', <QuestionOutlined />)}
      </Space>
      {!canDecide && disabledReason && <Typography.Text type="secondary">{disabledReason}</Typography.Text>}
      {panel && canDecide && (
        <Flex vertical gap={8} style={{ border: '1px solid #e5e7eb', borderRadius: 6, padding: 10, background: '#fafbfc' }}>
          {panel === 'confirm' && (
            <>
              <Select
                aria-label="Основание подтверждения"
                value={basis}
                onChange={setBasis}
                options={codes.confirm.map((c) => ({ value: c.code, label: c.label_ru }))}
                size="small"
              />
              {needsJustification && (
                <Alert
                  type="warning"
                  showIcon
                  title={`В карточке указано согласованное изменение: ${card.approved_change_ref}`}
                  description={<Input size="small" placeholder="Почему нарушение подтверждается" value={justification} onChange={(e) => setJustification(e.target.value)} aria-label="Обоснование подтверждения" />}
                />
              )}
            </>
          )}
          {panel === 'reject' && chips(codes.reject)}
          {panel === 'clarify' && chips(codes.clarify)}
          <Input.TextArea
            aria-label="Комментарий"
            autoSize={{ minRows: 2, maxRows: 6 }}
            value={comment}
            placeholder={panel === 'reject' ? (rejectEntry ? (card.prefill.reject_comments[rejectEntry.code] ?? 'Комментарий (необязательно)') : 'Комментарий (необязательно)') : 'Комментарий'}
            onChange={(e) => {
              setComment(e.target.value);
              setEdited(true);
            }}
          />
          {panel === 'confirm' && (
            <Select
              size="small"
              allowClear
              aria-label="Дальнейшее действие"
              placeholder="Дальнейшее действие в пределах полномочий (необязательно)"
              value={plannedAction ?? undefined}
              onChange={(v) => setPlannedAction(v ?? null)}
              options={codes.planned_action.map((c) => ({ value: c.code, label: c.label_ru }))}
            />
          )}
          {rejectEntry && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Для дообучения: {card.prefill.suggested_fixes[rejectEntry.code]}
            </Typography.Text>
          )}
          <Flex justify="space-between" align="center" gap={8}>
            <Typography.Text type={problem ? 'warning' : 'secondary'} style={{ fontSize: 12 }}>
              {problem ?? 'Enter — сохранить, Esc — закрыть'}
            </Typography.Text>
            <Button type="primary" danger={panel === 'confirm'} onClick={submit} disabled={Boolean(problem)} loading={busy} data-testid="save-decision">
              Сохранить
            </Button>
          </Flex>
        </Flex>
      )}
    </Flex>
  );
});
