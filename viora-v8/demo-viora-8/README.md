# Демо Viora Studio 8.0.0

Четыре прогона `tools/reel.py farm` (PROMPT-2, раздел 5, пункт 4), пересобраны 2026-10-11
после проверки автора.

## Главное: видео нет

Движка SHORTS в git пока нет (в ветке hoplite/smyrna-e9369463 только каркас, без tools/shorts.py).
Поэтому каждый отчёт начинается со строки «ПЛАН ГОТОВ, ВИДЕО НЕТ». Заглушка
viora-shorts/tests/fake_engine.py проверила только, что план принимается и длина в цели.
QR декодером, субтитры по словам, safe zone по пикселям, громкость и первый кадр не проверял
никто. В журнал роликов ни один демо-ролик не записан.

Настоящее в демо: проверка сайтов по сети, сценарий, план по схеме движка, 6 названий,
описание, закреп, TikTok, .srt (тайминги оценочные), обложки на настоящих скриншотах сайтов
(shots/shots.txt: оценка каждого кадра), анонс в канал, чек-лист из 20 пунктов.

| Папка | Что | Раскладка | Сценарий |
|---|---|---|---|
| a-post | ролик из поста «4 бесплатные находки» | three: верх это fixtures/top-loop.html (своё движение вместо геймплея, пока автор не дал запись игры) | написан моделью: fixtures/script-4-nahodki.json |
| b-html | ролик из HTML-файла «Ночной рейс», `--speed "0-4:1.5,4-8:0.6,8-12:2" --sound mix` | center_only | написан моделью: fixtures/script-html.json |
| c-farm | ферма одной командой из двух ссылок, без правок | three без своего видео: верх убран, напоминание в отчёте | каркас кода |
| d-english | английская версия (a) | three | написан моделью: fixtures/script-en.json |

Сайты (a): learn-anything.xyz, cadlookup.com и github.com/justxor/Linux- открылись.
builditapp.com по HTTP отвечает 200, но 10.10 запись headless-браузером закрывала защита от ботов:
в ролик не взят, строка об этом есть в анонсе, вернуть можно флагом `--retry-blocked`.
«Мегашпаргалка по Linux» найдена поиском: помечена «подтверди».

Скриншот learn-anything рисуется через WebGL и в headless без видеокарты выходит не всегда:
в (a) и (c) граф получился, в (d) нет, и героем стала страница шпаргалки (shots/shots.txt).

В каждой папке: report.md, script.md, script.json, plan.json, titles.md, description.txt,
pinned.txt, tiktok.txt, captions.srt, announce.txt (ссылка на ролик это метка PASTE_VIDEO_URL,
её меняет `reel.py announce <папка> --video-url URL`), cover-hero/punch/minimal.png,
cover-poster-9x16.png, cover-prompt.txt, meta.json, summary.json.
