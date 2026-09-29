# Запуск в Docker

Весь продукт (веб, API, распознавание, PostgreSQL, Redis, RabbitMQ) поднимается одной командой на любой машине с Docker.
Нативный запуск (`make dev`, [`LINUX.md`](LINUX.md)) не меняется: Docker — дополнительный способ.

Проверено в CI (`.github/workflows/docker.yml`, Ubuntu x86_64 без видеокарты) на каждом изменении: сборка,
`docker compose up -d`, все сервисы `healthy` за ≈ 35 с, вход, загрузка тестового комплекта (пд + рд) → «Готово» за 15 с,
протокол и картинка страницы через веб. Вариант с видеокартой NVIDIA на реальном железе ещё не проверялся.

## Коротко: запуск за 6 шагов

**1. Поставь Docker.**
- Linux (Ubuntu 22.04/24.04): `curl -fsSL https://get.docker.com | sudo sh`, затем `sudo usermod -aG docker $USER` и
  перелогинься.
- Windows 10/11: [Docker Desktop](https://www.docker.com/products/docker-desktop/) с движком WSL 2 (ставится мастером).
- macOS: Docker Desktop.
- Проверка: `docker compose version` → 2.20 или новее.
- В Docker Desktop (Settings → Resources) дай контейнерам хотя бы **4 ядра, 8 ГБ памяти, 30 ГБ диска**.

**2. Скачай код** (репозиторий приватный — нужен доступ на GitHub):

```bash
git clone https://github.com/Evgen74/inspector-ai.git
cd inspector-ai
```

**3. Запусти:**

```bash
docker compose up -d --build
```

Первый раз скачиваются базовые образы, пакеты Python/Node и три модели распознавания, собираются два образа:
приложение 4,9 ГБ и веб 60 МБ. В CI GitHub сборка идёт 2,5 минуты; дома — от нескольких минут до получаса, смотря
по интернету. Дальше запуск занимает секунды.

**4. Дождись готовности:** `docker compose ps` — у `postgres`, `redis`, `rabbitmq`, `api`, `ml-api`, `web` статус
`healthy`, у `migrate` — `Exited (0)` (он одноразовый, так и должно быть).

**5. Открой http://localhost:8080** и войди: логин `inspector`, пароль `Demo-Inspector-2026`.

**6. Загрузи комплект:** «Проверки» → «Загрузить комплект» → ZIP/7z/RAR, где документы лежат в папках `пд`, `рд`, `ид`
(стадия определяется по имени папки), или отдельные PDF. Лимиты: 500 МБ на документ, 5 ГБ на пакет. Когда обработка
дойдёт до «Готово», протокол откроется на странице проверки. Без видеокарты распознавание идёт на процессоре — это
медленнее, чем с ней (ниже).

### С видеокартой NVIDIA

Распознавание само выбирает видеокарту, если она доступна в контейнере, иначе работает на процессоре.

1. Подготовь хост:
   - Linux: драйвер NVIDIA ≥ 525 (`nvidia-smi` показывает карту) и
     [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
     Проверка: `docker run --rm --gpus all ubuntu nvidia-smi` — должна показать карту.
   - Windows: свежий драйвер NVIDIA для Windows + Docker Desktop на WSL 2 (поддержка GPU уже встроена).
2. Запусти с дополнительным файлом:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
   ```

3. Проверь, что выбрана видеокарта (в выводе должно быть `cuda`):

   ```bash
   docker compose exec api python /app/tools/models/gpu_check.py
   ```

   С GPU можно поднять число параллельных процессов распознавания: `INSPECTOR_UPLOAD_WORKERS=4` перед командой из
   шага 2 (по умолчанию 2).

### Что прислать, если что-то не так (или для замера скорости)

```bash
docker compose ps -a > ps.txt
docker compose logs --tail=300 api ml-api migrate > logs.txt
docker compose exec api python /app/tools/models/gpu_check.py > gpu.txt     # если есть видеокарта
docker compose exec api sh -c 'ls -t /data/runs'                            # последний прогон — первый в списке
docker compose cp api:/data/runs/<прогон>/recognize_summary.json .          # скорость распознавания
```

### Остановить, обновить, сбросить

```bash
docker compose stop                     # остановить (данные сохраняются)
docker compose up -d                    # снова запустить
git pull && docker compose up -d --build   # обновиться до новой версии
docker compose down -v                  # удалить всё, включая базу и загруженные комплекты
```

Порт 8080 занят — `INSPECTOR_HTTP_PORT=8081 docker compose up -d`, тогда адрес http://localhost:8081.
Если с видеокартой — повторяй `-f docker-compose.yml -f docker-compose.gpu.yml` в каждой команде `up`.

Ниже — подробности: как всё устроено, тома, параметры, данные организаторов, ограничения.

## 1. Что нужно

- Docker Engine 24+ (или Docker Desktop) с плагином Compose v2 (`docker compose version` ≥ 2.20).
- Linux x86_64 — основной вариант. Docker Desktop на macOS и Windows работает (см. раздел 8, ограничения).
- Свободно ≈ 15 ГБ на диске для сборки; готовый образ приложения занимает 4,9 ГБ (в основном библиотеки CUDA 12,
  которые тянет `onnxruntime-gpu`, — на процессоре они не используются, но нужны для варианта с видеокартой).
- Сеть при первой сборке: образы Docker Hub, пакеты Python/npm, три модели OCR (modelscope.cn, sha256 сверяется с
  `tools/models/manifest.json`). После сборки продукт сети не использует.
- Порт 8080 на хосте свободен (другой порт — `INSPECTOR_HTTP_PORT`).

## 2. Порядок старта и пароль

Сервисы стартуют по цепочке с проверками готовности (`depends_on: condition: service_healthy`): PostgreSQL, Redis,
RabbitMQ → одноразовая задача `migrate` (миграции и демо-учётка) → `api` и `ml-api` → `web`. Ход: `docker compose ps`,
`docker compose logs -f api`. `INSPECTOR_DEMO_PASSWORD` задаёт пароль демо-учётки при её первом создании; для уже
созданной базы — `docker compose run --rm migrate node dist/modules/auth/seed.js --reset-passwords`.

## 3. Как это устроено

| Сервис | Образ | Что делает |
|---|---|---|
| `web` | `inspector-ai/web` (nginx) | статическая сборка Vite, `/api` и `/metrics` проксирует на `api`; порт хоста 8080 |
| `api` | `inspector-ai/app` | NestJS (`node dist/main.js`, 0.0.0.0:3000); для загруженного комплекта запускает Python-конвейер (`python -m inspector_batch.cli …`) из той же среды |
| `ml-api` | `inspector-ai/app` | отрисовка страниц PDF для просмотра доказательств (0.0.0.0:8090, только внутри сети compose) |
| `migrate` | `inspector-ai/app` | одноразово: миграции БД и демо-учётка (обе операции идемпотентны) |
| `postgres` | `postgres:17` | база `inspector` |
| `redis` | `redis:7` | сессии |
| `rabbitmq` | `rabbitmq:3-management` | очередь загрузок (необязателен: без него задачи идут в процессе API) |

Один образ приложения (`docker/Dockerfile`, цель `app`) содержит Node 22 и Python 3.12 с окружением `uv sync --locked`
и тремя моделями OCR (`fetch_models.py` + `verify_models.py --ocr-only` — те же шаги, что `make fetch-models` и
`make verify-models-ocr`). Встраиватель e5 (0,5 ГБ) в образ **не входит**: путь загрузки и конвейер его не используют
(в Python-коде нет обращений к нему). Веб — цель `web` того же Dockerfile.

Наружу опубликован только порт web. API, ml-api, БД, Redis и RabbitMQ доступны лишь внутри сети compose; чтобы
заглянуть в них, используйте `docker compose exec` или добавьте `ports:` в локальный override.
Приложение работает в режиме `INSPECTOR_APP_ENV=demo` (вход обязателен, cookie без `Secure` — работает по http).
Пути внутри контейнеров те же, что в нативном запуске, но через переменные: `INSPECTOR_RUNS_ROOT=/data/runs`,
`INSPECTOR_CACHE_ROOT=/data/cache`, `INSPECTOR_MODELS_ROOT=/app/.models`.

## 4. Где лежат данные (тома)

| Том | Путь в контейнере | Содержимое |
|---|---|---|
| `runs` | `/data/runs` | загруженные комплекты (`uploads/…`), каталоги прогонов; общий для `api` и `ml-api` (ml-api читает оттуда загруженные PDF) |
| `cache` | `/data/cache` (он же `/app/.cache`) | кэши токенов и реестра, плитки страниц |
| `pgdata` | `/var/lib/postgresql/data` | база данных |
| `redisdata`, `rabbitdata` | `/data`, `/var/lib/rabbitmq` | сессии, очередь |

Имена томов в Docker получают префикс проекта: `inspector-ai_runs` и т. д. (`docker volume ls`).
Скопировать прогон на хост: `docker compose cp api:/data/runs/<run_id> ./run-copy`.

Параметры (необязательно; можно положить в файл `.env` рядом с `docker-compose.yml` — compose использует его только для
подстановок в самом compose-файле, в контейнеры он не попадает):

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `INSPECTOR_HTTP_PORT` | 8080 | порт web на хосте |
| `INSPECTOR_DB_PASSWORD` | `inspector` | пароль PostgreSQL и RabbitMQ внутри сети compose (только буквы и цифры) |
| `INSPECTOR_DEMO_PASSWORD` | `Demo-Inspector-2026` | пароль демо-учётки |
| `INSPECTOR_UPLOAD_WORKERS` | 2 | число процессов распознавания при загрузке; на машине с 8+ ядрами поднимите до 4–8 |
| `INSPECTOR_ML_API_TOKEN` | `inspector-internal-token` | общий секрет api ↔ ml-api |

## 5. Данные организаторов (необязательно)

Загрузка через интерфейс работает без данных организаторов. Чтобы обучающие объекты из пакета организаторов были
видны и рендерились, смонтируйте каталог `data_utf8` только для чтения:

```bash
INSPECTOR_DATA_HOST_PATH=/путь/к/data_utf8 \
  docker compose -f docker-compose.yml -f docker-compose.data.yml up -d
docker compose -f docker-compose.yml -f docker-compose.data.yml run --rm migrate   # назначить инспектора на обучающие объекты
```

Каталог монтируется в `/data/organizer:ro`, `INSPECTOR_DATA_ROOT` указывает на него в `api`, `ml-api` и `migrate`.
Данные организаторов в образы не попадают (`.dockerignore` исключает `data/`, `data_utf8/`, `ТЗ/`, `runs/`,
`.models/`, `deliverables/`, `*.onnx`).

## 6. Видеокарта NVIDIA (необязательно; на реальном железе ещё не проверено)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Override резервирует NVIDIA-устройства для `api` (там работает распознавание) и больше ничего не задаёт: исполнитель
выбирается автоматически (`--providers auto`: CUDA, если он реально работает, иначе CPU). Нужны драйвер NVIDIA и
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/) на хосте; проверка:
`docker compose exec api python /app/tools/models/gpu_check.py` (в образ входит `tools/models`). Ограничение числа
процессов на карте — `INSPECTOR_CUDA_MAX_WORKERS` (по умолчанию 4). Без видеокарты образ работает на CPU
(`onnxruntime-gpu` сам деградирует, это проверяет CI).

## 7. Логи, остановка, сброс

```bash
docker compose ps                       # состояние и health
docker compose logs -f api ml-api       # логи (JSON, по строке на событие)
docker compose logs --tail=200 migrate  # что сделала миграция
docker compose restart api              # перезапуск (незавершённые загрузки возобновляются)
docker compose stop                     # остановить, данные сохраняются
docker compose down                     # удалить контейнеры, тома сохраняются
docker compose down -v                  # полный сброс: удалить и тома (база, загрузки, кэши)
docker compose build --no-cache         # пересобрать образы с нуля
```

После обновления кода: `git pull && docker compose up -d --build`; миграции применяются задачей `migrate` сами.

Если порт 8080 занят: `INSPECTOR_HTTP_PORT=8081 docker compose up -d`. Если на хосте уже запущен нативный стек
(`make dev`), конфликта нет: контейнеры не публикуют 3000, 5173, 5432, 6379 и 8090.

## 8. Ограничения

- **Только CPU по умолчанию.** Скорость распознавания на CPU ниже, чем на CoreML/CUDA: комплект из сотен страниц
  обрабатывается заметно дольше. На Mac нативный запуск (`make dev`) заметно быстрее: внутри Docker Desktop на macOS
  нет доступа к CoreML и к видеокарте, а виртуальная машина ограничена своим числом ядер и памяти
  (Docker Desktop → Settings → Resources; для полных комплектов — от 4 ядер и 8 ГБ).
- Образ рассчитан на Linux x86_64. На arm64 (Docker Desktop на Apple Silicon, Linux aarch64) `uv sync` ставит обычный
  `onnxruntime`, образ меньше; сборка на arm64 в CI не проверяется.
- Загрузка буферизуется в памяти API (комплект до 5 ГБ требует соответствующего запаса памяти контейнера).
- nginx пропускает тело до 5300 МБ без буферизации на диск, таймауты чтения и записи — 1 час. Точные лимиты
  (500 МБ на документ, 5 ГБ на пакет) проверяет API и отвечает понятной ошибкой.
- Учётные данные БД и RabbitMQ по умолчанию простые (`inspector`), но эти сервисы недоступны снаружи сети compose.
  Для публичного развёртывания смените `INSPECTOR_DB_PASSWORD`, `INSPECTOR_DEMO_PASSWORD`, `INSPECTOR_ML_API_TOKEN`
  и поставьте перед web терминатор TLS.
- Модели OCR скачиваются при сборке образа (не при запуске): у собранного образа доступ к сети не нужен.
- Docker-запуск не заменяет нативный для разработки: изменения кода требуют `docker compose up -d --build`.
