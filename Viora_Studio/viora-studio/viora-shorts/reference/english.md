# Английский режим

Включается так: `reel.py farm ... --lang en` на один ролик или `reel.py prefs set language=en` насовсем.
Говорим с автором по-русски всегда. На английском уходят озвучка, субтитры, названия,
описание, закреп и подпись TikTok. Анонс в канал остаётся русским: канал русский.

## Кто пишет текст

Код не переводит. Сценарий пишет модель:

```bash
python3 tools/reel.py script post.txt --lang en --out script-en.json   # русская заготовка
# переписываешь каждую реплику по-английски, у пункта добавляешь "name_en", если имя русское
python3 tools/reel.py farm post.txt --lang en --script script-en.json
```

Проверка та же, плюс `E-LANG`: кириллица в английской реплике, названии или описании.

## Душа по-английски (адаптация `reference/soul.md`)

| Маркер | Русский | English |
|---|---|---|
| мнение одной строкой | «Лучший из трёх, без шуток» | "Best of the three, honestly." |
| шутка про быт | «Вечер спасён» | "There goes my evening plan." |
| тёплое обращение | без «ребята»: сразу к делу | no "hey guys": straight to the point |
| честный минус | «Пока сыроват» | "Still rough around the edges." |

Нельзя: "game changer", "unlock", "supercharge", "in today's video", "smash that like button",
"you won't believe". Это английский слоп, его режут так же, как наш канцелярит.

## Простыми словами по-английски (адаптация `reference/simple.md`)

- Одна мысль, до 12 слов, глагол в начале: "Type a topic. Get a roadmap."
- Термин объясняем через действие: "MCP server" -> "plugs into your AI agent and gives it new tools".
- Цифры цифрами: 3 sites, 12 lines, 896 KB.
- Без идиом, которые не поймёт школьник из другой страны: не "low-hanging fruit", а "easy win".

## Названия и описание

Шаблон тот же: `TEXT emoji #shorts #tags`, 5-7 вариантов от громкого к консервативному.
Капс только в громких, эмодзи максимум одно. Хэштеги английские: #shorts #free #usefulsites
плюс тема (#linux, #learning, #3d). Ссылки те же: Telegram и YouTube автора.

## Голос

По умолчанию en-US-AndrewMultilingualNeural (мужской) или en-US-AvaMultilingualNeural (женский).
Выбор движок проверяет сам, наш план только передаёт имя.
