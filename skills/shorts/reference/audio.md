# Звук

## Голос (TTS)
Цепочка `engine: auto`: edge-tts (бесплатно, неофициально, бывает пустой ответ: 6 попыток с паузой) ->
ElevenLabs (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, с таймингами символов) -> OpenAI TTS (`OPENAI_API_KEY`,
тайминги оценкой) -> Piper (`SHORTS_PIPER_MODEL`, офлайн). Принудительно: `SHORTS_TTS=edge|elevenlabs|openai|piper|silent`.
Голоса: `ru-male-1`, `ru-female-1`, `en-male-1`, `en-female-1`, `en-male-2`, `en-female-2` или прямое имя голоса.
Кэш по тексту: повторный рендер без сети. Выбор голоса запоминай в `prefs`.

## Музыка
Файл пользователя, ссылка YouTube (yt-dlp вытаскивает звук) или `assets/audio/bed.mp3` (своя, сгенерирована кодом, CC0).
Под голосом музыка на 10 дБ ниже голоса (`music.gain_db`), между фразами поднимается до 6 дБ (`duck_db`), фейды 0.3/0.8 с.
Биты: `beats файл|URL` (librosa: темп, доли, сильные доли, энергия).

## SFX
Свои, синтезированы кодом (CC0): `click`, `tick`, `pop`, `whoosh`, `hit`, `riser`, `shutter`, уровень -14 дБ.
Чужие библиотеки (Mixkit, ElevenLabs) в скилл не копируем: лицензии запрещают распространение.

## Громкость
Двухпроходный loudnorm: -14 LUFS, true peak -1.5 dBTP (QA: -14 +-1.5, пик не выше -1). Ролик понятен без звука.
