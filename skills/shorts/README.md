# SHORTS

Скилл для ИИ-агентов (Claude Code, Codex, Cursor и другие с форматом SKILL.md): делает вертикальные ролики
1080x1920 для YouTube Shorts, TikTok и Reels из сайтов, HTML-файлов, длинных видео, фильмов, текста и скриншотов.
Субтитры по словам, озвучка, музыка, вспышки со ссылкой и QR, QA-гейт, названия, описание и обложки.

## Установка за три шага
1. Положи папку `shorts/` в папку скиллов агента (`.claude/skills/`, `.agents/skills/` или рядом с проектом).
2. Нужны Python 3.11+ и ffmpeg с libass. Запусти `bash tools/install.sh` (создаст `.venv`, поставит зависимости,
   Chromium при необходимости, и покажет `doctor`).
3. Проверь: `bash tools/check_all.sh` (с `PYTHON=.venv/bin/python`, если venv). Всё зелёное = готово.

Дальше просто попроси агента: "сделай шортс про эти два сайта ...", "эдит из фильма ... под трек ...",
"нарежь моё видео на 3 шортса". Агент читает `SKILL.md`.

## Команды
`python3 tools/shorts.py --help`. Главные: `intake`, `prefs`, `validate`, `render`, `qa`, `meta`, `cover`,
`site-probe`, `moments`, `beats`, `edit`, `clips`, `doctor`, `all`.

## Переменные окружения (все необязательные)
| Имя | Зачем |
|---|---|
| `SHORTS_HOME` | корень скилла, если запускаешь не из папки |
| `SHORTS_MEMORY` | где хранить `prefs.json`, историю (по умолчанию `memory/`) |
| `SHORTS_CACHE` | кэш TTS, загрузок, транскриптов (по умолчанию `.cache/`) |
| `SHORTS_CHROME` | путь к браузеру |
| `SHORTS_TTS` | принудительный TTS: `edge`, `elevenlabs`, `openai`, `piper`, `silent` |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | платный голос с таймингами |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | генерация картинок для обложек (и голос OpenAI) |
| `SHORTS_IMAGE_PROVIDER` | `openai`, `gemini` или `none` |
| `SHORTS_YTDLP_COOKIES` | файл cookies, если YouTube просит вход |
| `SHORTS_NETWORK=1` | включить сетевые тесты |

## Структура
```
SKILL.md, ROUTER.md        точка входа и карта
reference/                 правила по темам (раскладка, субтитры, QR, звук, подписи, обложка, QA, эдиты)
schema/                    plan.schema.json (контракт v1), plan.example.json, safe_zones.json
tools/shorts.py            CLI
tools/shortskit/           движок: engine/ (layout, brand, tts, captions, graphics, clips, audio, render),
                           adapters/ (site, html, media, film, text_images), qa/, meta/, memory, planner, doctor
assets/                    шрифты OFL, пресеты бренда, своя музыка и геймплей (CC0), исходники
examples/                  планы демо-роликов
memory/                    prefs.example.json, experiments.md, metrics.md (личные файлы в .gitignore)
tests/                     unit, integration (офлайн-фикстуры), e2e, плохие случаи; network помечены
evals/cases.json           эталонные случаи для модели
docs/                      architecture.md, research-log.md
```
