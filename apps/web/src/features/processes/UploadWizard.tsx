/** Upload wizard: files, archives or a whole folder (drag-and-drop or pickers) → object and optional registry → result.
 * Limits of ТЗ §9.1 are shown up front. A folder keeps its relative paths, so the stage comes from the ПД / РД / ИД
 * folder names exactly as inside an archive. */
import { useMemo, useState } from 'react';
import { Alert, Button, Descriptions, Flex, Form, Input, List, Modal, Steps, Tag, Typography, Upload } from 'antd';
import type { UploadFile } from 'antd';
import { FileAddOutlined, FolderOpenOutlined, InboxOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router';
import { ProblemAlert } from '../../components/ProblemAlert';
import { formatBytes, formatInt, pluralRu } from '../../format';
import { DEFAULT_LIMITS, useUploadDocuments, useUploadLimits, type UploadResult, validateClientFiles } from './api';

const REGISTRY_EXT = ['.csv', '.xlsx', '.json'];
// Hidden and OS files of a picked folder («.DS_Store», «Thumbs.db», «__MACOSX/…»): never documents.
const SYSTEM_PATH = /(^|\/)(\.[^/]*|thumbs\.db|desktop\.ini|__macosx)(\/|$)/i;

/** Path inside a picked or dropped folder («Объект/ПД/АР.pdf»); '' for a file chosen on its own. */
export const folderPath = (f: File | undefined): string => {
  const rel = (f as (File & { webkitRelativePath?: string }) | undefined)?.webkitRelativePath ?? '';
  return rel.includes('/') ? rel : '';
};

const extOf = (name: string) => {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot).toLowerCase();
};

/** «.dwg — 3, .xlsx — 1, системные — 2» */
function skippedSummary(paths: string[]): string {
  const by = new Map<string, number>();
  for (const p of paths) {
    const key = SYSTEM_PATH.test(p) ? 'системные' : extOf(p) || 'без расширения';
    by.set(key, (by.get(key) ?? 0) + 1);
  }
  return [...by.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${k} — ${formatInt(n)}`)
    .join(', ');
}

export function UploadWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const limitsQuery = useUploadLimits(open);
  const limits = limitsQuery.data ?? DEFAULT_LIMITS;
  const mutation = useUploadDocuments();
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [registry, setRegistry] = useState<UploadFile[]>([]);
  // Files of a folder that are not documents (formats the product does not read, OS files): left out, summarised.
  const [skipped, setSkipped] = useState<string[]>([]);
  const [objectName, setObjectName] = useState('');
  const [address, setAddress] = useState('');
  const [result, setResult] = useState<UploadResult | null>(null);

  const check = useMemo(
    () => validateClientFiles(files.map((f) => ({ name: f.name, size: f.size ?? 0 })), limits),
    [files, limits],
  );
  const registryError = useMemo(() => {
    const r = registry[0];
    if (!r) return null;
    const ext = r.name.slice(r.name.lastIndexOf('.')).toLowerCase();
    return REGISTRY_EXT.includes(ext) ? null : 'Реестр: допустимы форматы CSV, XLSX, JSON.';
  }, [registry]);
  const valid = files.length > 0 && check.errors.size === 0 && !check.packageError;

  const reset = () => {
    setStep(0);
    setFiles([]);
    setRegistry([]);
    setSkipped([]);
    setObjectName('');
    setAddress('');
    setResult(null);
    mutation.reset();
  };
  const close = () => {
    reset();
    onClose();
  };

  const submit = async () => {
    const res = await mutation
      .mutateAsync({
        files: files.flatMap((f) => (f.originFileObj ? [f.originFileObj as File] : [])),
        registry: registry[0]?.originFileObj as File | undefined,
        objectName,
        address,
      })
      .catch(() => null);
    if (res) {
      setResult(res);
      setStep(2);
    }
  };

  // A file of a folder that is not a document is left out (with a summary); a file chosen on its own stays in the list,
  // with the reason, so the user sees why it is refused.
  const beforeUpload = (file: File) => {
    const rel = folderPath(file);
    if (rel && (SYSTEM_PATH.test(rel) || !limits.extensions.includes(extOf(file.name)))) {
      setSkipped((s) => [...s, rel]);
      return Upload.LIST_IGNORE;
    }
    return false;
  };
  const picker = {
    multiple: true,
    fileList: files,
    beforeUpload,
    // Folder files are listed by their path inside the folder: «ПД/АР.pdf» and «РД/АР.pdf» are different documents.
    onChange: (info: { fileList: UploadFile[] }) =>
      setFiles(info.fileList.map((f) => (folderPath(f.originFileObj) ? { ...f, name: folderPath(f.originFileObj) } : f))),
  };

  const footer =
    step === 0
      ? [
          <Button key="c" onClick={close}>
            Отмена
          </Button>,
          <Button key="n" type="primary" disabled={!valid} onClick={() => setStep(1)}>
            Далее
          </Button>,
        ]
      : step === 1
        ? [
            <Button key="b" onClick={() => setStep(0)}>
              Назад
            </Button>,
            <Button key="s" type="primary" loading={mutation.isPending} disabled={!!registryError} onClick={() => void submit()}>
              Загрузить и проверить
            </Button>,
          ]
        : [
            <Button key="c" onClick={close}>
              Закрыть
            </Button>,
            <Button
              key="o"
              type="primary"
              onClick={() => {
                const id = result?.process_id;
                close();
                if (id) navigate(`/processes/${id}`);
              }}
            >
              Открыть проверку
            </Button>,
          ];

  return (
    <Modal open={open} onCancel={close} title="Загрузка комплекта документов" width={720} footer={footer} destroyOnHidden>
      <Flex vertical gap={16}>
        <Steps
          size="small"
          current={step}
          items={[{ title: 'Файлы' }, { title: 'Объект и реестр' }, { title: 'Проверка' }]}
        />
        {step === 0 && (
          <>
            <Alert
              type="info"
              showIcon
              title="Требования к загрузке"
              description={`PDF, DOCX, XML и архивы ZIP, 7z, RAR. Не более ${formatBytes(limits.max_file_bytes)} на файл и ${formatBytes(
                limits.max_package_bytes,
              )} на весь пакет. Стадия (ПД, РД, ИД) определяется по реестру, а без него — по названиям папок и файлов.`}
            />
            <div className="upload-files">
              <Upload.Dragger
                {...picker}
                // Dropped folders are walked with their relative paths; a click does nothing (the two buttons choose).
                directory
                openFileDialogOnClick={false}
                // No `accept`: unsupported files must stay in the list with a Russian reason instead of being dropped silently.
                itemRender={(node, file) => {
                  const err = check.errors.get(file.name);
                  return (
                    <div>
                      {node}
                      {err && <Typography.Text type="danger">{err}</Typography.Text>}
                    </div>
                  );
                }}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">Перетащите сюда файлы, архивы или папку комплекта</p>
                <p className="ant-upload-hint">
                  В папке документы могут лежать в подпапках ПД, РД, ИД — стадия определится по их названиям, как в архиве
                </p>
                <Flex gap={8} justify="center" wrap onClick={(e) => e.stopPropagation()}>
                  <Upload {...picker} showUploadList={false}>
                    <Button icon={<FileAddOutlined />}>Выбрать файлы или архивы</Button>
                  </Upload>
                  <Upload {...picker} directory showUploadList={false}>
                    <Button icon={<FolderOpenOutlined />}>Выбрать папку</Button>
                  </Upload>
                </Flex>
              </Upload.Dragger>
            </div>
            <Typography.Text type="secondary">
              Выбрано: {formatInt(files.length)} {pluralRu(files.length, ['файл', 'файла', 'файлов'])}, {formatBytes(check.totalBytes)} из{' '}
              {formatBytes(limits.max_package_bytes)}
            </Typography.Text>
            {skipped.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`Из папки не взято ${formatInt(skipped.length)} ${pluralRu(skipped.length, ['файл', 'файла', 'файлов'])}: форматы, которые не читаются, и системные файлы`}
                description={skippedSummary(skipped)}
              />
            )}
            {check.packageError && <Alert type="error" showIcon title={check.packageError} />}
            {check.errors.size > 0 && (
              <Alert
                type="error"
                showIcon
                title={`Не принимаются файлов: ${check.errors.size}. Удалите их из списка или замените.`}
              />
            )}
          </>
        )}
        {step === 1 && (
          <>
            <Form layout="vertical">
              <Form.Item label="Наименование объекта">
                <Input aria-label="Наименование объекта" value={objectName} onChange={(e) => setObjectName(e.target.value)} maxLength={200} placeholder="Например: Жилой дом, ул. Тестовая 7" />
              </Form.Item>
              <Form.Item label="Адрес (необязательно)">
                <Input aria-label="Адрес" value={address} onChange={(e) => setAddress(e.target.value)} maxLength={300} />
              </Form.Item>
              <Form.Item
                label="Реестр комплекта (необязательно)"
                extra="CSV, XLSX или JSON со столбцами «файл» и «стадия» (ПД / РД / ИД), при желании «раздел»."
                validateStatus={registryError ? 'error' : undefined}
                help={registryError}
              >
                <Upload maxCount={1} fileList={registry} beforeUpload={() => false} onChange={(i) => setRegistry(i.fileList)} accept={REGISTRY_EXT.join(',')}>
                  <Button>Выбрать файл реестра</Button>
                </Upload>
              </Form.Item>
            </Form>
            {mutation.isError && <ProblemAlert error={mutation.error} />}
          </>
        )}
        {step === 2 && result && (
          <>
            <Alert
              type="success"
              showIcon
              title="Комплект принят, проверка поставлена в очередь"
              description="Статус обновляется автоматически на странице проверки. Когда протокол будет готов, появится ссылка на него."
            />
            <Descriptions size="small" column={1} items={[
              { key: 'p', label: 'Идентификатор проверки', children: <Typography.Text copyable>{result.process_id}</Typography.Text> },
              { key: 'o', label: 'Объект', children: result.object_id },
              { key: 'a', label: 'Принято файлов', children: formatInt(result.accepted.length) },
            ]} />
            {result.rejected.length > 0 && (
              <List
                size="small"
                header={<Typography.Text type="danger">Отклонено файлов: {result.rejected.length}</Typography.Text>}
                dataSource={result.rejected}
                renderItem={(r) => (
                  <List.Item>
                    <Flex vertical>
                      <Typography.Text strong>{r.name} <Tag color="red">{r.code}</Tag></Typography.Text>
                      <Typography.Text type="secondary">{r.detail}</Typography.Text>
                    </Flex>
                  </List.Item>
                )}
              />
            )}
          </>
        )}
      </Flex>
    </Modal>
  );
}
