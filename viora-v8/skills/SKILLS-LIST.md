# Какие скиллы скачать и в какой чат кинуть

Правило: качаешь архивом (zip) и кидаешь в нужный чат вместе с промптом. Описания простыми словами.
Я (агент) НЕ запускал эти скиллы, кроме трёх твоих (читал их SKILL.md) и yt-dlp. Описания остальных взяты с их страниц GitHub и из README, поэтому ИИ в другом чате должен сам открыть файл и проверить.

Как скачать:
- **Весь репозиторий:** кнопка `Code` -> `Download ZIP`, или ссылка из столбца "zip".
- **Только папку (рекомендую для больших репозиториев):** https://download-directory.github.io/ (вставляешь ссылку на папку, получаешь zip).
- **Через установщик:** `npx skills add <репозиторий>` на своём компьютере, потом заархивировать папку `.claude/skills` (или `.agents/skills`).

Условные обозначения: **MUST** взять обязательно, **OPT** по желанию. Лицензии указаны по GitHub.

---

## Чат 1: SKILLS "SHORTS" (движок, делает шортсы, эдиты, нарезки)

Промпт: `prompts/PROMPT-1-SHORTS.md`

| # | Скилл | Что делает (просто) | Лицензия | Что взять | Ссылка | zip |
|---|---|---|---|---|---|---|
| 1 | **brag** (твой) | Делает короткий ролик по одной идее: план, раскадровка, музыка, звуки, речь, рендер. Есть версия slim. | MIT | Как планировать ролик (рубрика вопросов, тон, раскадровка), как отдавать сборку рендереру | https://github.com/latent-spaces/brag | https://github.com/latent-spaces/brag/archive/refs/heads/main.zip |
| 2 | **video-shotcraft** (твой) | Промо-ролик из библиотеки готовых кадров (209 анимаций), звуки и музыка, подгонка под бит. | Apache-2.0 | Библиотеку движений и звуков, правила ритма и "паузы после главного" | https://github.com/Vincentwei1021/video-shotcraft | https://github.com/Vincentwei1021/video-shotcraft/archive/refs/heads/main.zip |
| 3 | **guizang-product-video-skill** (твой) | Читает стиль продукта и снимает ролик только в нём. | AGPL-3.0 | ТОЛЬКО идею "считать стиль проекта в токены" и проверки `check_delivery`. Код не копировать (AGPL заразная, если скилл публичный) | https://github.com/op7418/guizang-product-video-skill | https://github.com/op7418/guizang-product-video-skill/archive/refs/heads/main.zip |
| 4 | **HyperFrames** (HeyGen) | Агент пишет HTML-страницу, она превращается в видео. Есть готовые блоки, субтитры, курсор, музыка. | Apache-2.0 | Папки `skills/hyperframes`, `hyperframes-core`, `hyperframes-audio`, `embedded-captions`, `music-to-video`, `talking-head-recut`, `.agents/skills/captions-overlay`, `oversized-cursor`, `motion-doctrine`. Репозиторий очень большой, качай только папки | https://github.com/heygen-com/hyperframes | через download-directory (см. выше) |
| 5 | **Remotion skills** | Видео на React: правила, субтитры, звук, рендер. | в репозитории лицензия не указана | `remotion-best-practices`, `remotion-captions`, `remotion-multimedia`, `remotion-render` | https://github.com/remotion-dev/skills | https://github.com/remotion-dev/skills/archive/refs/heads/main.zip |
| 6 | **Youtube-clipper-skill** (op7418) | Качает ролик и субтитры, делит на главы по смыслу, режет нужные куски, вшивает субтитры. 2200 звёзд. | MIT | Скачивание, главы, нарезка, вшивание субтитров (нужны yt-dlp и ffmpeg с libass) | https://github.com/op7418/Youtube-clipper-skill | https://github.com/op7418/Youtube-clipper-skill/archive/refs/heads/main.zip |
| 7 | **beat-synced-edit** | Песня + видео, режет кадры в бит, делает готовый эдит. | MIT | Анализ битов и энергии, нарезку на сильных долях | https://github.com/ZiadAbdelkarim/beat-synced-edit | https://github.com/ZiadAbdelkarim/beat-synced-edit/archive/refs/heads/main.zip |
| 8 | **video-use** (browser-use) | Монтаж по транскрипту: вырезает паузы и слова-паразиты, субтитры, цвет, анимации поверх. 28 тысяч звёзд. Нужен ключ ElevenLabs для расшифровки (можно заменить на Whisper). | MIT | Идею "монтаж по тексту", EDL (список склеек), проверку швов | https://github.com/browser-use/video-use | https://github.com/browser-use/video-use/archive/refs/heads/main.zip |
| 9 | **playwright-skill** | Агент управляет браузером: открывает сайты, кликает, делает скриншоты. | MIT | Как надёжно ходить по сайтам | https://github.com/lackeyjb/playwright-skill | https://github.com/lackeyjb/playwright-skill/archive/refs/heads/main.zip |
| 10 | **karaoke-caption** (hqman) | Субтитры по словам, как в TikTok: подсветка слова, ASS и ffmpeg. Можно повторить стиль по скриншоту. | в репозитории лицензия не указана | Стиль субтитров по словам, ASS-генерацию | https://github.com/hqman/karaoke-caption | https://github.com/hqman/karaoke-caption/archive/refs/heads/main.zip |
| 11 | **anti-slop** (miqdadbadjuber) | Набор правил, как не делать "ИИ-дизайн": убирает градиенты, шаблонные шрифты и т.д. 5800 звёзд. | MIT | Правила и проверку дизайна (для QA-гейта) | https://github.com/miqdadbadjuber/anti-slop | https://github.com/miqdadbadjuber/anti-slop/archive/refs/heads/main.zip |
| 12 | **qr-code** (AlteredCraft) | Делает QR-коды (библиотека segno), задаёт цвета, размер, коррекцию ошибок. | в репозитории лицензия не указана | Скрипт `generate_qr.py`, идею с `uv run` | https://github.com/AlteredCraft/claude-code-plugins/tree/main/plugins/document-gen/skills/qr-code | через download-directory |
| 13 | **thumbnail + packaging** (hassancs91/claude-youtube-editor) | Делает обложки YouTube из концепции и стиля, проверяет кадры; `packaging` упаковывает название и описание. | MIT | Папки `.claude/skills/thumbnail`, `packaging`, `brand-setup`, `fake-screencast`, `suggest-sfx` | https://github.com/hassancs91/claude-youtube-editor | https://github.com/hassancs91/claude-youtube-editor/archive/refs/heads/main.zip |
| 14 | **image-skill** (mischacoster) | Генерация картинок через GPT-Image или Gemini Nano Banana: сам выбирает модель. Нужен ключ API. | MIT | Как подключить генератор картинок и выбрать провайдера | https://github.com/mischacoster/image-skill | https://github.com/mischacoster/image-skill/archive/refs/heads/main.zip |
| 15 | **frontend-design + canvas-design** (Anthropic) | Учит агента делать дизайн с характером, без шаблонов. Canvas делает постеры и картинки PNG. | в репозитории лицензия не указана (у скиллов свой LICENSE.txt) | Папки `skills/frontend-design`, `skills/canvas-design` | https://github.com/anthropics/skills | через download-directory (репозиторий большой) |

**OPT (по желанию):**
- **music-video-director-skill** (MIT): музыка + кадры в клип с ритмом и планом эмоций. https://github.com/guigulaoshi/music-video-director-skill
- **viral-clipper** (MIT): весь конвейер "ссылка YouTube -> шортс с субтитрами -> заливка", тяжёлый (GPU, сервер). Для идей, не для копирования. https://github.com/bertbertov/viral-clipper
- **yt-agent** (MIT): агент ищет, качает и каталогизирует YouTube через yt-dlp. https://github.com/jvogan/yt-agent
- **captions-cli** (MIT): субтитры по словам через Whisper и ffmpeg. https://github.com/jurczykpawel/captions-cli
- **PySceneDetect** (BSD-3): находит смены сцен, полезно для поиска ритма и нарезки. https://github.com/Breakthrough/PySceneDetect
- **marketingskills** (MIT): `copywriting`, `marketing-psychology`, `image`, `ab-testing` для текста и экспериментов. https://github.com/coreyhaines31/marketingskills
- **higgsfield-youtube-thumbnail** (MIT): обложки через платный сервис Higgsfield, нужен аккаунт. https://github.com/higgsfield-ai/skills

---

## Чат 2: Viora Studio 8.0.0 (твой скилл про посты, плюс видео про полезные сервисы)

Промпт: `prompts/PROMPT-2-VIORA-8.0.0.md`
Кидаешь в чат: `Viora_Studio.zip` версии 7.0.0 (последний), и архивы ниже. Движок SHORTS из чата 1 (он будет лежать в git) подключается внутрь.

| # | Скилл | Зачем в Viora | MUST/OPT | Ссылка |
|---|---|---|---|---|
| 1 | **brag** | как планировать ролик из поста: рубрика вопросов, тон, раскадровка | MUST | https://github.com/latent-spaces/brag |
| 2 | **video-shotcraft** | библиотека кадров, звуки, ритм для вставок и переходов | MUST | https://github.com/Vincentwei1021/video-shotcraft |
| 3 | **guizang-product-video-skill** | только идея: считывать стиль из проекта; для "Лачуги" (код не копировать из-за AGPL) | MUST (идея) | https://github.com/op7418/guizang-product-video-skill |
| 4 | **HyperFrames** | HTML -> видео для сцен про сервисы и для `html`-адаптера (фильм "Титаник" и карта) | MUST | https://github.com/heygen-com/hyperframes |
| 5 | **anti-slop** | проверка дизайна кадров и обложек | MUST | https://github.com/miqdadbadjuber/anti-slop |
| 6 | **qr-code** | QR в роликах | MUST | https://github.com/AlteredCraft/claude-code-plugins/tree/main/plugins/document-gen/skills/qr-code |
| 7 | **thumbnail + packaging** | обложки и упаковка названий (идеи для `reference/cover.md`) | MUST | https://github.com/hassancs91/claude-youtube-editor |
| 8 | **frontend-design + canvas-design** | вкус и дизайн-мышление | MUST | https://github.com/anthropics/skills |
| 9 | **Youtube-clipper-skill** | если из своих длинных видео нужны нарезки | OPT | https://github.com/op7418/Youtube-clipper-skill |
| 10 | **Remotion skills** | запасной рендерер и субтитры | OPT | https://github.com/remotion-dev/skills |
| 11 | **marketingskills** | `copywriting`, `marketing-psychology` для названий и призывов | OPT | https://github.com/coreyhaines31/marketingskills |
| 12 | **image-skill** | генерация картинок для обложек | OPT | https://github.com/mischacoster/image-skill |

---

## Порядок работы

1. **Сначала чат 1 (SHORTS).** Он пишет движок и кладёт его в git. Это самая тяжёлая часть.
2. **Потом чат 2 (Viora 8.0.0).** Он подключает движок, добавляет слой "пост -> ролик" и бренд VIORA. Если движок ещё не готов, он работает по контракту `spec/plan.schema.json` и тестирует на заглушке.
3. Оба чата читают: `research/click-and-watch.md`, `research/design-rules.md`, `spec/COMMON.md`, `refs/*`.
E
