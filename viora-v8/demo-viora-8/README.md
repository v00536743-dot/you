# Демо Viora Studio 8.0.0

Четыре прогона `tools/reel.py farm` из ТЗ (PROMPT-2, раздел 5, пункт 4). Собраны 2026-10-11
на ветке с Viora Studio 8.0.0. Настройки роликов перед прогоном: русский, YouTube Shorts и TikTok,
раскладка center_bottom (своего видео для верхней панели нет), QR да, стиль viora, мужской голос.

ВАЖНО: настоящего движка SHORTS в git ещё нет (в ветке hoplite/smyrna-e9369463 лежит только
каркас без tools/shorts.py). Поэтому рендер и QA сделала заглушка viora-shorts/tests/fake_engine.py:
видеофайла нет, контактного листа нет, пиксели (safe zone, QR декодером, громкость) никто не смотрел.
В каждом report.md это написано, пункты движка помечены «движок не проверял (заглушка)».
Всё остальное настоящее: проверка сайтов по сети, сценарий, план по схеме, названия, описание,
закреп, TikTok, .srt (тайминги оценочные), обложки, анонс в канал, чек-лист.

| Папка | Что | Команда |
|---|---|---|
| a-post | ролик из поста «4 бесплатные находки» | `reel.py farm viora-shorts/tests/fixtures/post-4-nahodki.txt` |
| b-html | ролик из HTML-файла (офлайн-фикстура «Ночной рейс») | `reel.py farm .../mini-film.html --script .../script-html.json --speed "0-4:1.5,4-8:0.6,8-12:2" --sound page` |
| c-farm | ферма одной командой из списка двух ссылок | `reel.py farm raw-links.txt` |
| d-english | английская версия ролика (a) | `reel.py farm .../post-4-nahodki.txt --lang en --script .../script-en.json` |

Сайты (a): learn-anything.xyz, cadlookup.com и github.com/justxor/Linux- открылись по сети.
builditapp.com сегодня отвечает по HTTP кодом 200, но в прототипе 10.10 запись headless-браузером
закрывала защита от ботов: в ролик не взят, вернуть можно флагом `--retry-blocked`.
«Мегашпаргалка по Linux» найдена поиском (README совпадает с описанием из поста): помечена «подтверди».

В каждой папке: report.md (итог и чек-лист 20 пунктов), script.md, plan.json, titles.md, description.txt,
pinned.txt, tiktok.txt, captions.srt, announce.txt, cover-*.png, cover-prompt.txt, meta.json, summary.json.
