# apps/web — веб-клиент «Инспектор ИИ»

React 19, Vite 8, TypeScript, Ant Design 6 (`ru_RU`), TanStack Query 5, React Router 8, OpenSeadragon 6.
Шрифт Golos Text самохостится, CDN во время работы не используется.

Общее описание системы, соответствие ТЗ, установка и список экранов — в [корневом README](../../README.md)
(разделы 6 и 11). Здесь только то, что нужно при работе с клиентом.

## Запуск

```bash
pnpm --filter @inspector/api dev       # API на :3000 (см. apps/api/README.md)
pnpm --filter @inspector/web dev       # http://127.0.0.1:5173, прокси /api и /metrics на API
pnpm --filter @inspector/web dev:mock  # без API: MSW отвечает по контракту (VITE_API_MOCK=1)
pnpm --filter @inspector/web build     # проверка типов + production-сборка в dist/
pnpm --filter @inspector/web test      # vitest + Testing Library
pnpm --filter @inspector/web gen:api   # перегенерация src/api/schema.gen.ts из OpenAPI
```

Переменные: `INSPECTOR_API_HOST` (по умолчанию `127.0.0.1`), `INSPECTOR_API_PORT` (`3000`), `INSPECTOR_WEB_PORT` (`5173`).

`gen:api` читает `packages/contracts/openapi/openapi.yaml` и оверлеи `apps/api/openapi/pending/*.yaml`; тест
`src/api/schema.gen.test.ts` падает, если сгенерированный файл устарел.

## Карта кода

- `src/api/schema.gen.ts` — типы из OpenAPI; `src/api/d1.ts` — хуки эндпоинтов протокола и доказательств.
- `src/contracts/protocol.ts` — TypeScript-вид `protocol.schema.json` и `finding_group.schema.json`; тесты проверяют
  каждую фикстуру по JSON Schema.
- `src/features/protocol` (рендер Приложения 2, страница, выгрузка), `src/features/evidence` (просмотрщик,
  геометрия; `pageSource.ts` — единственное место, знающее адреса сервиса рендера), `src/features/dashboard`,
  `src/features/verification`, `src/features/processes`, `src/features/normative`.
- `src/mocks` — обработчики MSW, типизированные сгенерированными типами; данные — фикстура D1 из
  `apps/api/fixtures/d1` и явно названные синтетические объекты `OBJ-SYNTH-*`.
- Подписи статусов берутся из `packages/contracts/enums.yaml` (подключается при сборке, `src/contracts/enums.ts`);
  точный код контракта лежит в подсказке каждой метки и в `data-code`. Ошибки показывают русский текст сервера и
  «Код обращения» (`request_id`).

Демо D1 целиком: `pnpm --filter @inspector/api fixture:d1` создаёт каталог запуска `runs/d1-fixture-tyumen`,
`POST /api/v1/admin/batch-runs/import {"run_dir":"d1-fixture-tyumen"}` импортирует его, изображения страниц отдаёт
ml-api (`make ml-api-dev`, `INSPECTOR_ML_API_URL`).
