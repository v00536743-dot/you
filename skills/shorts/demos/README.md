# Демо SHORTS 1.0 (2026-10-11)

Сами видео (12-20 МБ) в git не кладём (правило: большие видео не коммитим). Здесь для каждого демо: QA-отчёт,
подписи, `.srt`, контактный лист (2 кадра/с), первый кадр, обложки 16:9 и 9:16, manifest и итоговый план.
Видео пересобираются командами ниже (кэш TTS и загрузок сохраняется в `.cache/`).

| Демо | Источник | Раскладка | Язык / платформы | Длина | QA (strict) |
|---|---|---|---|---|---|
| `a-sites-ru` | learn-anything.xyz + cadlookup.com (`site`), реальный edge-tts | `three` | ru / Shorts + TikTok | 26.3 с | PASSED, 1 warn (короткие порции из-за длинных имён сайтов) |
| `b-html-en` | локальный HTML: `vt`-шим и верхняя панель `html:` через `__seek`, замедление 0.4x и ускорение 2x, кинетический текст | `top_center` | en / Shorts + TikTok + Reels | 16.4 с | PASSED |
| `c-film-edit` | Tears of Steel (Blender, CC-BY 3.0, 720p с download.blender.org), 19 кадров в бит 112 BPM, замедление на пике | `center_only` | en / Shorts + TikTok | 20.3 с | PASSED |
| `d-long-video-clip` | тот же фильм как "длинное видео": окно по громкости, склейкам и речи, faster-whisper (base) даёт субтитры | `center_bottom` | en / Shorts | 27.7 с | PASSED |

Пересборка (из папки скилла):
```bash
python3 tools/shorts.py all schema/plan.example.json --out out/demo-a                    # сеть: сайты + edge-tts
python3 tools/shorts.py all examples/b-html-film.plan.json --out out/demo-b
python3 tools/shorts.py edit --video tears_of_steel_720p.mov --music assets/audio/bed.mp3 --length 20 \
  --title "TEARS OF STEEL" --lang en --handle VioraStudio --link https://t.me/VioraStudio --brand punch -o c.plan.json
python3 tools/shorts.py all c.plan.json --out out/demo-c
python3 tools/shorts.py clips --video tears_of_steel_720p.mov -n 2 --length 30 --lang en -o out/d-clips   # потом хук и CTA в план
python3 tools/shorts.py all examples/d-long-video-clip.plan.json --out out/demo-d
```
`examples/c-film-edit.plan.json` и `examples/d-long-video-clip.plan.json` ссылаются на `/tmp/media/tos720.mov`:
поменяй путь на свой файл.

## Что посмотрено глазами (пункт 13)
- **a:** метка "2 САЙТА БЕСПЛАТНО" на первом кадре, живой раннер сверху; ввод "Linux", окно приветствия сайта
  закрывается, список дистрибутивов с зумом на клик; CAD Lookup: ввод "gear with 12 teeth", сетка шестерёнок;
  вспышка ника на 14 с, QR в конце над результатами "robot arm". Субтитры по смыслу ("Пишешь тему," / "например Linux,").
- **b:** орбиты на звёздном поле, плавное замедление, текст фразами на чередующемся фоне, QR в конце, всё на английском.
- **c:** быстрые склейки, заголовок на первом кадре, ник на середине, QR в последние 3 с, переход в первый кадр.
  Замечание: кадр на 9.5 с тёмный (сцена в темноте), при ручной правке его стоит заменить.
- **d:** хук "YOU BROKE MY HEART", реплики субтитрами по словам, ник и QR в рабочей зоне, низ с брендом.

## Что НЕ проверено
- YouTube как источник в этой песочнице: поиск работает, но скачивание и heatmap для IP сервера требуют входа
  ("Sign in to confirm you're not a bot"). В начале сессии heatmap и куски Big Buck Bunny скачивались. Логика heatmap
  покрыта офлайн-тестом на синтетике; для реальной работы с сервера нужен файл cookies (`SHORTS_YTDLP_COOKIES`).
- Генерация картинок (ключей нет): обложки сделаны из кадров, промпт лежит в `cover/prompt.md`.
- ElevenLabs, OpenAI TTS и Piper: код есть, без ключей и модели не запускался.
