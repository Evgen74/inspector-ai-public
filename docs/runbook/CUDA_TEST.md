# Проверка «Инспектор ИИ» на видеокарте NVIDIA (≈ 20–40 минут)

Цель: подтвердить, что распознавание само выбирает CUDA и работает на видеокарте, и снять скорость.

Нужно: Linux x86_64 (Ubuntu 22.04/24.04), видеокарта NVIDIA, драйвер **≥ 525** (`nvidia-smi` должен показывать карту),
~10 ГБ свободного места, интернет только на время установки.

## 1. Установка

```bash
sudo apt-get update && sudo apt-get install -y git make unzip libarchive-tools
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env   # менеджер Python (uv)
git clone git@github.com:Evgen74/inspector-ai.git && cd inspector-ai/services/ml   # приватный репозиторий: нужен доступ
uv sync --locked            # Python 3.12 и onnxruntime-gpu с библиотеками CUDA 12 (~2 ГБ, один раз)
cd ../.. && make fetch-models   # 3 модели OCR (~15 МБ), sha256 проверяется
make gpu-check              # ДОЛЖНО быть: cuda. Пришли вывод этой команды целиком
```

## 2. Замер скорости на реальных документах

Положи PDF (например, папку `ид` из комплекта «Полярная, 17», лучше сканы) в `~/pol/incoming/`:

```bash
mkdir -p ~/pol/incoming && cp -r /путь/к/папке/ид ~/pol/incoming/
cd inspector-ai/services/ml
uv run --locked python -m inspector_registry.adhoc prepare \
    --upload-dir ~/pol --object-name "Полярная, 17 (ИД)" --object-id OBJ-UPLOAD-00c0da01
uv run --locked inspector-batch --data-root ~/pol/dataroot --run-id cuda-test \
    recognize --object OBJ-UPLOAD-00c0da01 --workers 4 2>&1 | tee ~/cuda-test.log
```

В начале вывода будет строка «Исполнитель распознавания: CUDA …». В конце — число страниц и скорость (стр/мин).

Для сравнения тот же прогон на CPU (необязательно, если есть время):

```bash
uv run --locked inspector-batch --data-root ~/pol/dataroot --run-id cpu-test \
    recognize --object OBJ-UPLOAD-00c0da01 --workers 4 --providers cpu 2>&1 | tee ~/cpu-test.log
```

## 3. Что прислать обратно

- вывод `make gpu-check` и `nvidia-smi` (модель карты, драйвер);
- файлы `~/cuda-test.log` (и `~/cpu-test.log`, если делал);
- файл `inspector-ai/runs/cuda-test/recognize_summary.json`;
- CPU машины: `lscpu | head -20`.

Если что-то упало — пришли последние 50 строк вывода. Настройки: `INSPECTOR_CUDA_MAX_WORKERS=N` (по умолчанию 4),
`INSPECTOR_CUDA_DEVICE=1` (если карт несколько). Подробности — `inspector-ai/docs/runbook/LINUX.md`, раздел 7.
