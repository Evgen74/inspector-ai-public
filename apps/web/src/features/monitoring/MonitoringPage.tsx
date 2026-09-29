/** «Мониторинг» (module 11): services, request metrics, queue, disk, recent log events and threshold alerts. */
import { useState } from 'react';
import { Alert, Badge, Card, Col, Descriptions, Flex, Progress, Row, Select, Statistic, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { Link } from 'react-router';
import { ProblemAlert } from '../../components/ProblemAlert';
import { BatchRunsPanel } from '../../pages/MonitoringPage';
import { formatBytes, formatDateTime, formatDateTimeSec, formatInt } from '../../format';
import { type MonitoringOverview, useMonitoringOverview } from './api';

type Service = MonitoringOverview['services'][number];
type LogLine = MonitoringOverview['logs'][number];

const STATUS_RU: Record<string, string> = {
  PENDING: 'Загружена',
  PARSING: 'Обработка',
  READY: 'Протокол готов',
  VERIFYING: 'Верификация',
  COMPLETED: 'Завершена',
  FINALIZED: 'Финализирована',
  FAILED: 'Ошибка',
};

const LEVEL_RU: Record<string, string> = { error: 'ошибка', warn: 'предупреждение', warning: 'предупреждение', info: 'сведения', debug: 'отладка' };
const LEVEL_COLOR: Record<string, string> = { error: 'red', warn: 'gold', warning: 'gold', info: 'blue', debug: 'default' };

function ms(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${formatInt(v)} мс`;
}

function uptime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h} ч ${m} мин` : `${m} мин ${s % 60} с`;
}

function serviceText(s: Service): string {
  if (s.status === 'up') return s.latency_ms ? `работает, ${formatInt(s.latency_ms)} мс` : 'работает';
  return s.detail ? `недоступен: ${s.detail}` : 'недоступен';
}

export function MonitoringPage() {
  const [interval, setIntervalMs] = useState<number>(10_000);
  const q = useMonitoringOverview(100, interval > 0 ? interval : false);
  const o = q.data;

  const logColumns: TableColumnsType<LogLine> = [
    { title: 'Время', dataIndex: 'timestamp', width: 180, render: (t: string) => <Typography.Text style={{ whiteSpace: 'nowrap' }}>{formatDateTimeSec(t)}</Typography.Text> },
    { title: 'Уровень', dataIndex: 'level', width: 130, render: (l: string) => <Tag color={LEVEL_COLOR[l] ?? 'default'}>{LEVEL_RU[l] ?? l}</Tag> },
    { title: 'Событие', dataIndex: 'event', width: 160, render: (e: string | null) => e ?? '—' },
    { title: 'Сообщение', dataIndex: 'message', ellipsis: true },
    { title: 'Запрос', dataIndex: 'request_id', width: 120, ellipsis: true, render: (r: string | null) => (r ? <Typography.Text type="secondary">{r.slice(0, 8)}</Typography.Text> : '—') },
  ];

  return (
    <Flex vertical gap={16} data-testid="monitoring-page">
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Мониторинг
        </Typography.Title>
        <Flex gap={12} align="center" wrap>
          <Link to="/admin/selftest">Самопроверка</Link>
          <a href="/metrics" target="_blank" rel="noreferrer">
            Экспорт метрик Prometheus
          </a>
          <Select
            size="small"
            value={interval}
            onChange={setIntervalMs}
            aria-label="Период обновления"
            style={{ width: 170 }}
            options={[
              { value: 5_000, label: 'Обновлять: 5 с' },
              { value: 10_000, label: 'Обновлять: 10 с' },
              { value: 30_000, label: 'Обновлять: 30 с' },
              { value: 0, label: 'Не обновлять' },
            ]}
          />
        </Flex>
      </Flex>

      {q.isError && <ProblemAlert error={q.error} />}

      {o && o.alerts.length > 0 && (
        <Flex vertical gap={8} data-testid="alerts">
          {o.alerts.map((a) => (
            <Alert key={a.code} type={a.severity === 'critical' ? 'error' : 'warning'} showIcon title={a.message} />
          ))}
        </Flex>
      )}
      {o && o.alerts.length === 0 && <Alert type="success" showIcon title="Пороговые значения не превышены" />}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card title="Состояние сервисов" loading={q.isLoading} size="small">
            <Descriptions size="small" column={1}>
              {(o?.services ?? []).map((s) => (
                <Descriptions.Item key={s.code} label={s.name}>
                  <Badge
                    data-testid={`service-${s.code}`}
                    status={s.status === 'up' ? 'success' : s.optional ? 'warning' : 'error'}
                    text={serviceText(s)}
                  />
                </Descriptions.Item>
              ))}
              <Descriptions.Item label="Проверено">{formatDateTime(o?.time)}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card title="Запросы к API (последние 5 минут)" loading={q.isLoading} size="small">
            <Row gutter={16}>
              <Col span={6}>
                <Statistic title="Запросов в минуту" value={o?.http.rate_per_min ?? 0} />
              </Col>
              <Col span={6}>
                <Statistic title="Задержка p95" value={o?.http.p95_ms ?? '—'} suffix={o?.http.p95_ms != null ? 'мс' : undefined}
                  styles={{ content: { color: o && o.http.p95_ms != null && o.http.p95_ms > (o.thresholds.p95_ms ?? 500) ? '#C62828' : undefined } }} />
              </Col>
              <Col span={6}>
                <Statistic title="Ответов 5xx" value={o?.http.errors_5xx ?? 0}
                  styles={{ content: { color: o && o.http.errors_5xx > 0 ? '#C62828' : undefined } }} />
              </Col>
              <Col span={6}>
                <Statistic title="Ответов 4xx" value={o?.http.errors_4xx ?? 0} />
              </Col>
            </Row>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Всего с запуска: {formatInt(o?.http.total_requests)} запросов, из них 5xx: {formatInt(o?.http.total_errors_5xx)}; медиана {ms(o?.http.p50_ms)}.
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Система" loading={q.isLoading} size="small">
            <Flex vertical gap={8}>
              <div>
                <Typography.Text type="secondary">Процессор</Typography.Text>
                <Progress percent={o?.system.cpu_percent ?? 0} size="small" status={o && o.system.cpu_percent > (o.thresholds.cpu_percent ?? 80) ? 'exception' : 'normal'} format={(p) => `${p}%`} />
              </div>
              <div>
                <Typography.Text type="secondary">Память</Typography.Text>
                <Progress percent={o?.system.memory_used_percent ?? 0} size="small" format={(p) => `${p}%`} />
              </div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Нагрузка (1 мин): {o?.system.load_avg_1m ?? '—'} на {o?.system.cpu_count ?? '—'} ядер · процесс API: {o?.system.process_rss_mb ?? '—'} МБ · работает {o ? uptime(o.system.uptime_s) : '—'}
              </Typography.Text>
            </Flex>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Очередь и проверки" loading={q.isLoading} size="small">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Режим заданий">
                {o?.queue.mode === 'rabbitmq' ? <Tag color="green">RabbitMQ</Tag> : <Tag color="gold">внутри процесса (резервный)</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="В очереди">{formatInt(o?.queue.size)}</Descriptions.Item>
              {Object.entries(o?.queue.processes_by_status ?? {}).map(([k, n]) => (
                <Descriptions.Item key={k} label={STATUS_RU[k] ?? k}>
                  {formatInt(n)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Диск" loading={q.isLoading} size="small">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Каталог запусков (runs/)">{formatBytes(o?.disk.runs_bytes)}</Descriptions.Item>
              <Descriptions.Item label="Свободно">{formatBytes(o?.disk.free_bytes)}</Descriptions.Item>
            </Descriptions>
            <Progress percent={o?.disk.used_percent ?? 0} size="small" status={o?.disk.used_percent != null && o.disk.used_percent > (o.thresholds.disk_percent ?? 90) ? 'exception' : 'normal'} format={(p) => `занято ${p}%`} />
          </Card>
        </Col>
      </Row>

      <Card title="Последние события журнала API" size="small" extra={<Typography.Text type="secondary">{o?.logs.length ?? 0} строк</Typography.Text>}>
        <Table<LogLine>
          rowKey={(r) => `${r.timestamp}-${r.request_id ?? ''}-${r.message}`}
          size="small"
          columns={logColumns}
          dataSource={o?.logs ?? []}
          loading={q.isLoading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 800 }}
        />
      </Card>
      <BatchRunsPanel />
    </Flex>
  );
}
