# shorts-farm

Из плана (plan.json) делает вертикальный шортс 1080x1920: сверху свой "залипательный" фон, в центре запись сайтов с курсором и субтитрами, снизу блок с каналом.

```bash
uv venv v && . v/bin/activate && uv pip install playwright edge-tts && playwright install ffmpeg
python make_short.py plan.test.json out/
```

Нужны ffmpeg и google-chrome. Озвучка: edge-tts (бесплатно, иногда отвечает пустотой, скрипт повторяет попытку).
Формат сцены: `say` (как читать), `badge` (капс в кадре), `actions` (что делать на сайте и в какую секунду).
Подмены написания в субтитрах: `subs` (читаем "лёрн энисинг", показываем "learn-anything").
