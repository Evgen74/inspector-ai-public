/**
 * Object indicator (08 §3.4–3.5): colour always comes with an icon and text; the reasons computed by the server
 * are in the tooltip, the contract code in `data-code`. Red is reserved for confirmed violations.
 */
import { Space, Tag, Tooltip, Typography } from 'antd';
import type { Indicator } from '../api/d1';
import { enumLabel } from '../contracts/enums';

export const INDICATOR_STYLE: Record<string, { bg: string; fg: string; icon: string; text: string }> = {
  RED: { bg: '#C62828', fg: '#fff', icon: '⛔', text: 'Нарушения подтверждены' },
  YELLOW: { bg: '#F2A900', fg: '#1f1f1f', icon: '⚠', text: 'Требует действий' },
  GREEN: { bg: '#2E7D32', fg: '#fff', icon: '✔', text: 'Нарушений нет' },
  NONE: { bg: '#8C8C8C', fg: '#fff', icon: '◌', text: 'Нет результата' },
};

export function IndicatorTag({ indicator, compact = false }: { indicator: Indicator; compact?: boolean }) {
  const s = INDICATOR_STYLE[indicator.color] ?? INDICATOR_STYLE.NONE!;
  const tip = (
    <div>
      <div style={{ fontWeight: 600 }}>
        {s.text}
      </div>
      {indicator.reasons.map((r) => (
        <div key={r.code}>• {r.text}</div>
      ))}
    </div>
  );
  return (
    <Tooltip title={tip}>
      <span
        data-code={indicator.color}
        data-testid="indicator"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '1px 8px',
          borderRadius: 4,
          background: s.bg,
          color: s.fg,
          fontSize: 12.5,
          fontWeight: 600,
          whiteSpace: 'nowrap',
          lineHeight: '20px',
        }}
      >
        <span aria-hidden>{s.icon}</span>
        {compact ? null : s.text}
        {compact ? <span className="sr-only">{s.text}</span> : null}
      </span>
    </Tooltip>
  );
}

const UPLOAD_SHORT: Record<string, { mark: string; color: string }> = {
  UPLOADED: { mark: '✓', color: 'green' },
  PARTIAL: { mark: '◐', color: 'gold' },
  MISSING: { mark: '–', color: 'default' },
};

/** [ПД ✓][РД ✓][ИД –] chips (ТЗ §9.1 upload statuses). */
export function UploadChips({ status }: { status: { pd: string | null; rd: string | null; id: string | null } }) {
  const chip = (stage: 'ПД' | 'РД' | 'ИД', code: string | null) => {
    if (!code) {
      return (
        <Tag key={stage} style={{ marginInlineEnd: 0 }}>
          {stage} ?
        </Tag>
      );
    }
    const kind = code.split('_')[1] ?? '';
    const s = UPLOAD_SHORT[kind] ?? { mark: '?', color: 'default' };
    return (
      <Tooltip key={stage} title={`${enumLabel('StageUploadStatus', code)} (${code})`}>
        <Tag color={s.color} data-code={code} style={{ marginInlineEnd: 0 }}>
          {stage} {s.mark}
        </Tag>
      </Tooltip>
    );
  };
  return (
    <Space size={2}>
      {chip('ПД', status.pd)}
      {chip('РД', status.rd)}
      {chip('ИД', status.id)}
    </Space>
  );
}

export function CountCell({ n, danger, warn }: { n: number; danger?: boolean; warn?: boolean }) {
  if (n === 0) return <Typography.Text type="secondary">0</Typography.Text>;
  return (
    <Typography.Text strong type={danger ? 'danger' : warn ? 'warning' : undefined}>
      {n}
    </Typography.Text>
  );
}
