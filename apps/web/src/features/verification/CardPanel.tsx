/**
 * The evidence card of one atomic finding (ТЗ §9.2 п.4, 05 VER-01…VER-14): expected / actual, sources with
 * file_id, SHA-256, стадия, шифр, редакция, статус утверждения, лист / страница and bbox, обоснование, уровень
 * риска (ordering only), the inspector's decision and reason, the AI dispute and the decision history.
 */
import { useState } from 'react';
import { Alert, Button, Collapse, Descriptions, Flex, Input, Space, Table, Tag, Timeline, Tooltip, Typography } from 'antd';
import { CheckCircleOutlined, ExclamationCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { enumLabel } from '../../contracts/enums';
import { formatDateTime, shortHash } from '../../format';
import type { CardSourceView, Dispute, EvidenceCardView } from './types';

export const STATUS_MARK: Record<string, { text: string; color: string }> = {
  PENDING: { text: '⏳ Ожидает', color: 'default' },
  CONFIRMED_VIOLATION: { text: '✅ Подтверждено', color: 'red' },
  NEGATIVE_VERIFIED: { text: '❌ Отклонено', color: 'green' },
  CLARIFICATION_REQUIRED: { text: '❓ Требует уточнения', color: 'gold' },
};

export function StatusTag({ status, dispute }: { status: string | null; dispute?: boolean }) {
  if (!status) return <Tag>не требует решения</Tag>;
  const m = STATUS_MARK[status] ?? { text: enumLabel('InspectorStatus', status), color: 'default' };
  return (
    <Tag color={m.color} data-status={status} style={{ marginInlineEnd: 0 }}>
      {m.text}
      {dispute ? ' · спор с ИИ' : ''}
    </Tag>
  );
}

const DELTA_DIRECTION_RU: Record<string, string> = {
  ABSENT: 'отсутствует',
  HIGHER: 'больше эталона',
  LOWER: 'меньше эталона',
  DIFFERENT: 'отличается',
  MISSING: 'отсутствует',
};

/** Russian sentence for the machine delta {actual, expected, direction} (no raw JSON in the UI). */
export function deltaText(delta: Record<string, unknown> | null | undefined): string | null {
  if (!delta) return null;
  const has = (v: unknown) => v !== null && v !== undefined && v !== '';
  const { expected, actual, direction } = delta as { expected?: unknown; actual?: unknown; direction?: unknown };
  const dir = String(direction ?? '').toUpperCase();
  if (dir === 'ABSENT' || (has(expected) && !has(actual))) {
    return has(expected) ? `В РД отсутствует ${String(expected)}` : 'Значение отсутствует';
  }
  const parts: string[] = [];
  if (has(expected)) parts.push(`ожидалось ${String(expected)}`);
  if (has(actual)) parts.push(`фактически ${String(actual)}`);
  const label = DELTA_DIRECTION_RU[dir];
  if (label) parts.push(label);
  return parts.length ? parts.join(', ') : null;
}

function valueText(v: unknown): string {
  if (v === null || v === undefined || v === '') return 'нет данных';
  return String(v);
}

function boxesOf(s: CardSourceView): number {
  return (s.geometry?.boxes?.length ?? 0) + (s.geometry?.polygons?.length ?? 0);
}

function SourcesTable({ sources }: { sources: CardSourceView[] }) {
  return (
    <Table<CardSourceView>
      size="small"
      pagination={false}
      rowKey={(s) => `${s.file_id}#${s.pdf_page_number}`}
      dataSource={sources}
      scroll={{ x: true }}
      columns={[
        {
          title: 'Стадия',
          key: 'stage',
          render: (_, s) => (
            <Tooltip title={s.role ? enumLabel('EvidenceRole', s.role) : undefined}>
              <Tag color={s.stage === 'PD' ? 'blue' : 'red'} style={{ marginInlineEnd: 0 }}>
                {s.stage_ru}
              </Tag>
            </Tooltip>
          ),
        },
        {
          title: 'Файл',
          key: 'file',
          render: (_, s) => (
            <Flex vertical>
              <Typography.Text style={{ fontSize: 12 }} strong>
                {s.file_id}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 11 }} copyable={s.file_sha256 ? { text: s.file_sha256 } : false}>
                SHA-256 {shortHash(s.file_sha256)}
              </Typography.Text>
            </Flex>
          ),
        },
        { title: 'Шифр', key: 'code', render: (_, s) => <span style={{ fontSize: 12 }}>{s.document_code ?? '—'}</span> },
        { title: 'Ред.', key: 'rev', render: (_, s) => s.revision ?? '—' },
        { title: 'Утверждение', key: 'approval', render: (_, s) => <span style={{ fontSize: 12 }}>{s.approval_status ? enumLabel('ApprovalStatus', s.approval_status) : '—'}</span> },
        {
          title: 'Лист / стр.',
          key: 'page',
          render: (_, s) => (
            <span style={{ whiteSpace: 'nowrap' }}>
              л. {s.sheet_number ?? '—'} / стр. {s.pdf_page_number}
              {s.is_anchor ? <Tag style={{ marginInlineStart: 4 }}>опорная</Tag> : null}
              {s.location_page ? <Tag color="purple" style={{ marginInlineStart: 4 }}>местоположение</Tag> : null}
            </span>
          ),
        },
        { title: 'bbox', key: 'bbox', render: (_, s) => (boxesOf(s) ? `${boxesOf(s)} фр.` : 'стр.') },
      ]}
    />
  );
}

export function DisputeBanner({
  dispute,
  canDecide,
  busy,
  onResolve,
}: {
  dispute: Dispute;
  canDecide: boolean;
  busy: boolean;
  onResolve: (resolution: 'INSPECTOR_UPHELD' | 'AI_UPHELD' | 'KEPT_CLARIFICATION', comment: string | null) => void;
}) {
  const [insisting, setInsisting] = useState(false);
  const [comment, setComment] = useState('');
  return (
    <Alert
      type="warning"
      showIcon
      icon={<ExclamationCircleOutlined />}
      data-testid="dispute-banner"
      title={`ИИ не согласен с отклонением (${enumLabel('DecisionRejectReason', dispute.rejection_reason)})`}
      description={
        <Flex vertical gap={8}>
          <Typography.Text style={{ fontSize: 13 }}>{dispute.ai_comment}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Комментарий инспектора: {dispute.inspector_comment}
          </Typography.Text>
          {canDecide && !insisting && (
            <Space wrap>
              <Button size="small" danger onClick={() => onResolve('AI_UPHELD', null)} loading={busy}>
                Подтвердить нарушение
              </Button>
              <Button size="small" onClick={() => onResolve('KEPT_CLARIFICATION', null)} loading={busy}>
                Оставить на уточнении
              </Button>
              <Button size="small" onClick={() => setInsisting(true)}>
                Настоять на отклонении…
              </Button>
            </Space>
          )}
          {canDecide && insisting && (
            <Flex vertical gap={6}>
              <Input.TextArea
                autoFocus
                rows={3}
                placeholder="Собственное обоснование: почему отклонение верно, несмотря на возражение ИИ"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                aria-label="Обоснование отклонения"
              />
              <Space>
                <Button size="small" type="primary" disabled={!comment.trim()} loading={busy} onClick={() => onResolve('INSPECTOR_UPHELD', comment.trim())}>
                  Настоять на отклонении
                </Button>
                <Button size="small" onClick={() => setInsisting(false)}>
                  Отмена
                </Button>
              </Space>
            </Flex>
          )}
        </Flex>
      }
    />
  );
}

export function CardPanel({ card }: { card: EvidenceCardView }) {
  const checklist = card.field_checklist;
  const full = checklist.filter((f) => f.present).length;
  return (
    <Flex vertical gap={10} data-testid="evidence-card">
      <Flex vertical gap={2}>
        <Space size={6} wrap>
          <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
            {card.card_no ?? 'Б.—'}
          </Tag>
          <StatusTag status={card.statuses.inspector_status} dispute={Boolean(card.open_dispute)} />
          {card.param.matrix_scope === 'FREE_SEARCH' && <Tag color="purple">свободный поиск</Tag>}
          {card.criticality_level === 'CRITICAL_SUSPEND' && <Tag color="volcano">Критическое</Tag>}
        </Space>
        <Typography.Title level={5} style={{ margin: '4px 0 0' }}>
          {card.param.label}
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {card.location_text} · {card.param.code}
          {card.param.rule_version ? ` · правило ${card.param.rule_version}` : ''}
        </Typography.Text>
      </Flex>
      <Descriptions
        size="small"
        column={1}
        bordered
        styles={{ label: { width: 118, padding: '5px 8px', fontSize: 12.5 }, content: { padding: '5px 8px', fontSize: 13 } }}
        items={[
          { key: 'expected', label: 'Ожидается (эталон)', children: <span data-testid="expected">{valueText(card.values.expected)}</span> },
          { key: 'actual', label: 'Фактически', children: <span data-testid="actual">{valueText(card.values.actual)}</span> },
          {
            key: 'result',
            label: 'Расхождение',
            children: [card.values.comparison_result_ru ?? '—', deltaText(card.values.delta)].filter(Boolean).join(' · '),
          },
          { key: 'criticality', label: 'Критичность', children: card.criticality ?? '—' },
          {
            key: 'risk',
            label: 'Уровень риска',
            children: (
              <Flex vertical>
                <span>
                  {card.risk_level ? enumLabel('RiskLevel', card.risk_level) : '—'}
                  {card.confidence !== null ? ` · уверенность ${Math.round(card.confidence * 100)}%` : ''}
                </span>
                <Typography.Text type="secondary" style={{ fontSize: 11.5 }}>
                  {card.risk_note}
                </Typography.Text>
              </Flex>
            ),
          },
          { key: 'approved', label: 'Согласованное изменение', children: card.approved_change_ref.toUpperCase() === 'NONE' ? 'нет' : card.approved_change_ref },
          {
            key: 'decision',
            label: 'Решение инспектора',
            children: card.inspector.status && card.inspector.status !== 'PENDING' ? (
              <Flex vertical>
                <span>
                  {STATUS_MARK[card.inspector.status]?.text}
                  {card.inspector.reason_code ? ` · ${enumLabel('DecisionRejectReason', card.inspector.reason_code)}` : ''}
                  {card.inspector.basis_code ? ` · ${enumLabel('DecisionConfirmBasis', card.inspector.basis_code)}` : ''}
                  {card.inspector.clarify_code ? ` · ${enumLabel('DecisionClarifyBasis', card.inspector.clarify_code)}` : ''}
                </span>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {card.inspector.user?.full_name}, {formatDateTime(card.inspector.decided_at)}
                </Typography.Text>
              </Flex>
            ) : (
              'ожидает решения'
            ),
          },
        ]}
      />
      <SourcesTable sources={card.sources} />
      {card.rationale && (
        <Alert type="info" showIcon icon={<InfoCircleOutlined />} title="Обоснование" description={<span style={{ fontSize: 13 }}>{card.rationale}</span>} />
      )}
      <Collapse
        size="small"
        items={[
          {
            key: 'checklist',
            label: `Поля карточки по п. 9.2.4 ТЗ: ${full} из ${checklist.length}`,
            children: (
              <Flex vertical gap={2} data-testid="field-checklist">
                {checklist.map((f) => (
                  <Space key={f.key} size={6}>
                    {f.present ? <CheckCircleOutlined style={{ color: '#389e0d' }} /> : <ExclamationCircleOutlined style={{ color: f.partial ? '#d48806' : '#bfbfbf' }} />}
                    <span style={{ fontSize: 12.5 }}>
                      {f.label_ru}
                      {!f.present && f.partial ? ' — частично' : ''}
                    </span>
                  </Space>
                ))}
              </Flex>
            ),
          },
          {
            key: 'history',
            label: `История решений: ${card.history.length}`,
            children: card.history.length ? (
              <Timeline
                items={card.history.map((h) => ({
                  key: h.decision.decision_id,
                  content: (
                    <Flex vertical>
                      <span style={{ fontSize: 12.5 }}>
                        {STATUS_MARK[h.decision.effective_status ?? '']?.text ?? h.decision.decision} · {h.user?.full_name ?? h.decision.decided_by}
                      </span>
                      <Typography.Text type="secondary" style={{ fontSize: 11.5 }}>
                        {formatDateTime(h.decision.decided_at)} · {h.decision.comment}
                      </Typography.Text>
                      {h.decision.ai_comment && (
                        <Typography.Text type="secondary" style={{ fontSize: 11.5 }}>
                          {h.decision.ai_comment}
                        </Typography.Text>
                      )}
                    </Flex>
                  ),
                }))}
              />
            ) : (
              <Typography.Text type="secondary">Решений ещё не было.</Typography.Text>
            ),
          },
        ]}
      />
    </Flex>
  );
}
