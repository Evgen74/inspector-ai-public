/**
 * Status chips. Text = Russian label from enums.yaml, the exact contract code in a tooltip and in `data-code`
 * (08 §3.4). Colour always comes with text.
 */
import { Badge, Tag, Tooltip, Typography } from 'antd';
import { CheckOutlined, CopyOutlined } from '@ant-design/icons';
import { enumLabel } from '../contracts/enums';
import { shortHash } from '../format';
import { INDICATOR_STYLE } from './indicator';

const STAGE_COLORS: Record<string, string> = {
  PD: 'blue',
  RD: 'geekblue',
  ID: 'purple',
  RD_ID_MIXED: 'cyan',
  UNKNOWN: 'default',
};

export function StageTag({ stage, resolved }: { stage: string; resolved?: string | null }) {
  const label = enumLabel('ManifestStage', stage);
  const short = stage === 'RD_ID_MIXED' ? 'РД/ИД' : stage === 'UNKNOWN' ? 'Не указана' : label;
  const tip = resolved && resolved !== stage ? `${label} · определена: ${enumLabel('DocStage', resolved)}` : label;
  return (
    <Tooltip title={`${tip} (${stage})`}>
      <Tag color={STAGE_COLORS[stage] ?? 'default'} data-code={stage}>
        {short}
      </Tag>
    </Tooltip>
  );
}

export function SplitTag({ split }: { split: string | null }) {
  if (!split) return <Typography.Text type="secondary">—</Typography.Text>;
  const hidden = split === 'TEST_HIDDEN';
  return (
    <Tooltip title={split}>
      <Tag color={hidden ? 'volcano' : 'green'} data-code={split}>
        {enumLabel('ManifestSplit', split)}
      </Tag>
    </Tooltip>
  );
}

const LOCAL_STATUS_COLORS: Record<string, string> = { PRESENT: 'success', RECOVERED: 'processing', MISSING_ON_DISK: 'error' };

export function LocalStatusTag({ status }: { status: string }) {
  return (
    <Tooltip title={status}>
      <Tag color={LOCAL_STATUS_COLORS[status] ?? 'default'} data-code={status}>
        {enumLabel('LocalFileStatus', status)}
      </Tag>
    </Tooltip>
  );
}

const INDICATOR_STATUS: Record<string, 'error' | 'warning' | 'success' | 'default'> = {
  RED: 'error',
  YELLOW: 'warning',
  GREEN: 'success',
  NONE: 'default',
};

export function IndicatorBadge({ color }: { color: string }) {
  return (
    <Tooltip title={color === 'NONE' ? 'Индикация появится после первого протокола' : INDICATOR_STYLE[color]?.text}>
      <span data-code={color}>
        <Badge status={INDICATOR_STATUS[color] ?? 'default'} text={(INDICATOR_STYLE[color] ?? INDICATOR_STYLE.NONE!).text} />
      </span>
    </Tooltip>
  );
}

export function HashText({ value }: { value: string | null | undefined }) {
  if (!value) return <Typography.Text type="secondary">—</Typography.Text>;
  return (
    <Typography.Text
      code
      copyable={{ text: value, icon: [<CopyOutlined key="c" />, <CheckOutlined key="d" />], tooltips: ['Копировать SHA-256', 'Скопировано'] }}
      title={value}
    >
      {shortHash(value)}
    </Typography.Text>
  );
}
