/** Protocol downloads (AG-04's export files through the API) and the version picker option. */
import { Button, Dropdown, Space, Tooltip } from 'antd';
import { DownloadOutlined, FilePdfOutlined, FileWordOutlined } from '@ant-design/icons';
import { exportUrl, type ProtocolFileFormat, type ProtocolVersion } from '../../api/d1';
import { protocolStatusText } from '../../contracts/labels';
import { formatDateTime } from '../../format';

const FORMAT_LABEL: Record<ProtocolFileFormat, string> = { docx: 'DOCX', pdf: 'PDF', json: 'JSON' };

export function versionOption(v: ProtocolVersion) {
  return {
    value: v.run_id,
    label: `${protocolStatusText(v.status, v.web_version)} · ${formatDateTime(v.generated_at)}${v.is_latest ? ' · текущая' : ''}`,
  };
}

export function ExportButtons({ objectId, version }: { objectId: string; version: ProtocolVersion }) {
  const has = (f: ProtocolFileFormat) => version.formats.includes(f);
  const missing = 'Файл ещё не сформирован';
  return (
    <Space.Compact>
      <Tooltip title={has('docx') ? 'Скачать протокол в формате Word' : missing}>
        <Button icon={<FileWordOutlined />} href={has('docx') ? exportUrl(objectId, version.run_id, 'docx') : undefined} disabled={!has('docx')}>
          DOCX
        </Button>
      </Tooltip>
      <Tooltip title={has('pdf') ? 'Скачать протокол в формате PDF' : missing}>
        <Button icon={<FilePdfOutlined />} href={has('pdf') ? exportUrl(objectId, version.run_id, 'pdf') : undefined} disabled={!has('pdf')}>
          PDF
        </Button>
      </Tooltip>
      <Dropdown
        menu={{
          items: (['json'] as ProtocolFileFormat[]).map((f) => ({
            key: f,
            label: (
              <a href={exportUrl(objectId, version.run_id, f)} download>
                {FORMAT_LABEL[f]} — канонический протокол
              </a>
            ),
          })),
        }}
      >
        <Button icon={<DownloadOutlined />} aria-label="Другие форматы" />
      </Dropdown>
    </Space.Compact>
  );
}

