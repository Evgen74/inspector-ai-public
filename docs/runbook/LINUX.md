# Запуск на Linux (Ubuntu 22.04 / 24.04)

Продукт работает на Linux так же, как на macOS: тот же код, те же `make`-цели. Отличается только исполнитель
распознавания документов, и он выбирается автоматически: **CoreML** на macOS → **CUDA** на Linux/Windows с рабочей
видеокартой NVIDIA → иначе **CPU**. Никакой ручной настройки для этого не требуется (раздел 7).

Доказательство, что базовый прогон проходит на чистом Linux без GPU: `.github/workflows/ci.yml`
(ubuntu-latest: `make setup`, `make lint`, `make test`, `make test-db`, OCR-проверка на CPU).

> Пометка о проверке. Команды разделов 1–6 и 8 собраны по официальным инструкциям PostgreSQL, Redis, NodeSource и uv
> и повторяют шаги CI. Прогнать их на чистой Ubuntu автору сборки было негде (была только macOS, без Docker), поэтому
> самое надёжное подтверждение — зелёный запуск CI. Путь CUDA на реальной видеокарте не проверялся вообще:
> проверены выбор исполнителя (модульные тесты с подменой onnxruntime), lock-файл зависимостей и деградация на CPU.

## 0. Что должно быть на машине

| Компонент | Версия | Зачем |
|---|---|---|
| Python | 3.12 (ставит `uv`) | ML-часть (`services/ml`), пакетный запуск `inspector-batch` |
| uv | любой свежий | окружение и lock-файл Python |
| Node.js + corepack | 22.x, pnpm 12.6 (версия зашита в `package.json`) | API (NestJS) и веб (React) |
| PostgreSQL | 17 | база веб-режима |
| Redis | **7.0 или новее** (команда `EXPIRE … NX`) | сессии |
| RabbitMQ | 3.x, необязателен | очередь задач; без него задачи идут в процессе API |
| libarchive | системная (`libarchive-tools`) | распаковка 7z/rar при загрузке пакета документов |
| Tesseract | необязателен (`tesseract-ocr`, `tesseract-ocr-osd`) | подсказка ориентации страницы, если OCR-проба неоднозначна |

Порты по умолчанию (все на 127.0.0.1): API 3000, веб 5173, ml-api 8090, PostgreSQL 5432, Redis 6379, RabbitMQ 5672.

## 1. Базовые пакеты

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg lsb-release git make build-essential libarchive-tools
# необязательно: Tesseract для проверки ориентации страниц
sudo apt-get install -y tesseract-ocr tesseract-ocr-osd
```

## 2. PostgreSQL 17 (репозиторий PGDG)

Ubuntu 22.04 содержит PostgreSQL 14, 24.04 — 16, поэтому нужен репозиторий PGDG:

```bash
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-17
sudo systemctl enable --now postgresql
```

Роль и пароль для приложения (по умолчанию Ubuntu разрешает TCP-вход только с паролем):

```bash
sudo -u postgres psql -c "CREATE ROLE inspector LOGIN CREATEDB PASSWORD 'inspector';"
```

Файл `.env` в корне репозитория (его читает `Makefile`; `PGUSER`/`PGPASSWORD` нужны цели `make db-create`):

```bash
cat > .env <<'EOF'
INSPECTOR_DATABASE_URL=postgresql://inspector:inspector@localhost:5432/inspector
INSPECTOR_TEST_DATABASE_URL=postgresql://inspector:inspector@localhost:5432/inspector_test
PGUSER=inspector
PGPASSWORD=inspector
EOF
```

Проверка: `pg_isready -h localhost` → `localhost:5432 - accepting connections`.

## 3. Redis 7+

Ubuntu 24.04 содержит Redis 7.0 (подходит: `sudo apt-get install -y redis-server`). В Ubuntu 22.04 — Redis 6.0, который
не подходит; поставьте из официального репозитория Redis:

```bash
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update && sudo apt-get install -y redis
sudo systemctl enable --now redis-server
```

Проверка: `redis-cli ping` → `PONG`; `redis-server --version` → 7.x или 8.x.

## 4. RabbitMQ (необязательно)

```bash
sudo apt-get install -y rabbitmq-server
sudo systemctl enable --now rabbitmq-server
```

Учётная запись `guest/guest` работает только с локальной машины, а именно этого и ждёт API (`amqp://127.0.0.1:5672`).
Без брокера продукт работает: API пишет предупреждение и выполняет задачи в собственном процессе.

## 4a. Альтернатива пунктам 2–4: Docker Compose

Если Docker уже стоит, PostgreSQL 17, Redis 8 и RabbitMQ поднимает один файл в корне репозитория:

```bash
docker compose -f docker-compose.infra.yml up -d      # остановить: ... down (данные остаются в томах; -v — стереть)
```

Порты и учётные данные совпадают с умолчаниями приложения: `postgresql://localhost:5432/inspector` (суперпользователь —
ваш логин ОС без пароля, поэтому `.env` из пункта 2 не нужен), `redis://127.0.0.1:6379/0`, `amqp://127.0.0.1:5672`
(guest/guest, интерфейс http://127.0.0.1:15672). Всё слушает только 127.0.0.1. Если в оболочке не задана переменная
`USER`, экспортируйте её или задайте `POSTGRES_USER`. Файл минимален и стандартен, но в среде разработки, где он
создавался, Docker не запускался, так что запуск не проверялся.

## 5. Node.js 22, pnpm, Python 3.12, uv

```bash
# Node 22 (NodeSource) и pnpm через corepack (версия pnpm закреплена в package.json)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo corepack enable pnpm

# uv и Python 3.12 (uv сам скачает 3.12, системный не нужен; на 24.04 подойдёт и apt-овский python3.12)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
```

Проверка: `node --version` → v22.x, `uv --version`. Файл `.python-version` в репозиторий не добавляйте (правило проекта).
`Makefile` берёт `python3.12` из PATH, а если его нет, оставляет выбор за `uv`.

## 6. Установка и модели

```bash
git clone <адрес репозитория> hackaton && cd hackaton
make setup SKIP_MODEL_CHECK=1      # uv sync --locked (Python), pnpm install --frozen-lockfile
make fetch-models                  # ОДИН РАЗ, нужен интернет: 3 модели OCR (≈ 80 МБ) в .models/ocr
make verify-models-ocr             # sha256 моделей по tools/models/manifest.json
```

* Как получаются модели. Модели в репозиторий не коммитятся, их pinned-список (размер и sha256) лежит в
  `tools/models/manifest.json`. `make fetch-models` (скрипт `tools/models/fetch_models.py`, только стандартная
  библиотека) скачивает три файла из публичного релиза RapidOCR v3.9.2 и принимает файл, только если размер и sha256
  совпали с манифестом; проверенный файл кладётся атомарно. Это единственный шаг с сетью. Сам продукт сеть не
  использует никогда.
* Офлайн: скопируйте каталог `.models/` с другой машины (или укажите его в `INSPECTOR_MODELS_ROOT`) и выполните
  `make verify-models-ocr`.
* `make verify-models` без `-ocr` проверяет ещё и эмбеддер e5 (≈ 0,5 ГБ, Hugging Face). Конвейер распознавания
  его не использует, поэтому на новой машине эта команда сообщит «отсутствует: hf/…», и это нормально.
* Одноразовая проверка на синтетической странице: `make gpu-check` (какой исполнитель выбран) и
  `cd services/ml && uv run --locked python ../../tools/ci/ocr_smoke.py` (распознаёт русскую страницу).

## 7. Видеокарта NVIDIA (необязательно)

Ничего настраивать не нужно: `--providers auto` (по умолчанию) сам выбирает лучший исполнитель.

Порядок выбора: **CoreML** (macOS с CoreML EP) → **CUDA** → **CPU**. CUDA выбирается, только если сессия CUDA на модели
детектора действительно создалась и работает (`get_providers()[0] == 'CUDAExecutionProvider'`): `onnxruntime-gpu` числит
CUDA-провайдер в списке и без драйвера, а потом молча уходит на CPU, поэтому одного списка мало. Результат проверки
кэшируется на процесс, решение пишется в лог (`ocr.provider_resolved`) и печатается в консоль
(«Исполнитель распознавания: CUDA (видеокарта NVIDIA) — выбран автоматически»).

**Что поставить.**

1. Драйвер NVIDIA версии не ниже 525 (для CUDA 12): `sudo ubuntu-drivers install` или пакет `nvidia-driver-5xx`,
   затем перезагрузка. Проверка: `nvidia-smi` показывает карту и версию драйвера.
2. Больше ничего: на Linux x86_64 и Windows `uv sync --locked` ставит `onnxruntime-gpu` (сборка CUDA 12) вместе с
   pip-пакетами `nvidia-cuda-runtime-cu12`, `nvidia-cudnn-cu12`, `nvidia-cublas-cu12` и др. (примерно 2 ГБ), а код
   вызывает `onnxruntime.preload_dlls()`. Системный CUDA Toolkit не нужен. Версия `onnxruntime-gpu` ограничена `<1.27`:
   начиная с 1.27 колёса на PyPI собраны под CUDA 13 (драйвер ≥ 580).
3. Альтернатива без pip-библиотек NVIDIA: системный драйвер + CUDA 12.x + cuDNN 9 (`libcudnn9-cuda-12` из репозитория
   NVIDIA), пути к библиотекам в `LD_LIBRARY_PATH`; `preload_dlls` тогда ничего не найдёт в site-packages, а
   загрузчик возьмёт системные.

**Проверка одной командой** (печатает, что выбрано):

```bash
cd services/ml && uv run --locked python -c "from inspector_docproc.models import resolve_provider_mode as r; print(r('auto'))"
# cuda | cpu | coreml
make gpu-check          # то же с пояснением, почему выбран именно он
```

**Без видеокарты** (или при неисправном драйвере) продукт работает на CPU: `onnxruntime-gpu` без GPU остаётся
рабочим CPU-рантаймом, `auto` даёт `cpu`, а `make gpu-check` печатает причину («сессия CUDA перешла на CPU…» или
ошибку загрузки библиотеки). Принудительно: `--providers cpu` / `--providers cuda`. Явный `cuda` без работающей
карты: предупреждение и откат на CPU; в замороженном/строгом прогоне (`--strict-providers`, `--hidden-run`) — ошибка
`CONFIG_INVALID`, подмен нет.

**Как работает CUDA-режим.** Детектор и распознаватель идут на GPU, оба с динамическими формами (холсты 1600²/3200²
нужны только CoreML). Каждый рабочий процесс держит свой контекст CUDA и три сессии (≈ 0,5–1,5 ГБ видеопамяти), а ядра
GPU всё равно выполняются по очереди, поэтому пул рабочих процессов в режиме CUDA ограничен 4 (в том числе при явном
`--workers`, а API запускает загрузку с `--workers 8`). Изменить: `INSPECTOR_CUDA_MAX_WORKERS=N`; выбрать карту:
`INSPECTOR_CUDA_DEVICE=1`; ограничить арену видеопамяти на сессию: `INSPECTOR_CUDA_MEM_LIMIT_MB=1024`. Схема
«один процесс-владелец GPU для всех рабочих», как у CoreML (`ocr/detserver.py`), не использована сознательно: она
держится на статических холстах в общей памяти и не покрывает распознаватель.

Результаты разных исполнителей различаются в последних знаках чисел. Версия конвейера включает исполнителя
(`docproc-…+cuda.<хэш>`), поэтому кэш PageTokens хранится отдельно для CoreML, CUDA и CPU и никогда не смешивается.

## 8. База данных, запуск, порты

```bash
make db-create db-migrate          # создать базу inspector и применить миграции apps/api/drizzle
make db-seed                       # демо-пользователь (единственная роль INSPECTOR)
make dev                           # ml-api :8090, API :3000, веб :5173; Ctrl-C останавливает всё
```

* Веб: http://127.0.0.1:5173 (проксирует `/api` на API), API: http://127.0.0.1:3000/api/v1, ml-api: http://127.0.0.1:8090.
* Всё привязано к 127.0.0.1. Чтобы открыть снаружи, поставьте перед ним обратный прокси (nginx/Caddy) или задайте
  `INSPECTOR_API_HOST` (см. `.env.example`); ml-api защищайте `INSPECTOR_ML_API_TOKEN`.
* Пакетный режим без веб-части (PostgreSQL и Redis не нужны):
  `cd services/ml && uv run --locked inspector-batch recognize --object <ОБЪЕКТ>`; данные организаторов — в
  `INSPECTOR_DATA_ROOT` (по умолчанию `data_utf8/`).
* Проверка целиком: `make lint`, `make test` (тесты на данных организаторов без данных пропускаются),
  `make test-db` (нужны PostgreSQL и Redis).

## 9. Отличия от macOS, о которых стоит знать

| Тема | macOS | Linux |
|---|---|---|
| Исполнитель | CoreML (детектор), CPU (распознаватель) | CUDA (оба), иначе CPU |
| Защита от сна на время прогона | `caffeinate` | `systemd-inhibit` (если есть; сервер без systemd просто не засыпает); отключить: `--allow-sleep` |
| Регистр в именах файлов | ФС без учёта регистра | ФС с учётом регистра: реестр (`inspector_registry`) сопоставляет пути по NFC/NFD и без регистра сам |
| Архивы | libarchive из системы | `apt install libarchive-tools`; `unrar` не используется нигде (правило проекта) |
| PostgreSQL/Redis | Homebrew | apt или `docker-compose.infra.yml` |
| Кэш CoreML | `.cache/coreml` | не создаётся |

## 10. Если что-то не так

* `make gpu-check` печатает `CPU`, хотя карта есть: смотрите причину в выводе; `nvidia-smi` должен работать, драйвер ≥ 525;
  `uv run --locked python -c "import onnxruntime as o; print(o.__version__, o.get_available_providers())"` должен
  показать `CUDAExecutionProvider` (иначе поставился CPU-`onnxruntime`: проверьте, что платформа Linux x86_64, а не
  aarch64).
* `libcudnn.so.9: cannot open shared object file`: не поставились pip-пакеты NVIDIA (сеть при `uv sync`) или их
  перехватывает другой `LD_LIBRARY_PATH`; повторите `uv sync --locked`.
* Нехватка видеопамяти: уменьшите `INSPECTOR_CUDA_MAX_WORKERS` или задайте `INSPECTOR_CUDA_MEM_LIMIT_MB`.
* `make db-create` просит пароль или отказывает: проверьте `PGUSER`/`PGPASSWORD` в `.env` (пункт 2).
* Сессии не работают, ошибка про `EXPIRE`: Redis старше 7.0 (пункт 3).
