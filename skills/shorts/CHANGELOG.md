# Changelog

## 1.0.0 - 2026-10-11
Первая версия.
- Движок: раскладка (`three`, `top_center`, `center_bottom`, `center_only`, центр от 55%), safe-зоны YouTube/TikTok/Reels,
  5 пресетов бренда, шрифты OFL с кириллицей, субтитры по словам (ASS, 2-3 слова по смыслу), TTS с цепочкой запасных
  и кэшем, музыка с ducking, свои SFX, loudnorm -14 LUFS, вспышки CTA и QR из центра, петля.
- Адаптеры: `site` (Playwright, курсор, зум на клик, честный пропуск защищённых сайтов), `html` (детерминированный
  захват: `__seek`, `frame(dt)` или подмена времени), `video`/`film` (yt-dlp кусками, моменты по heatmap, громкости,
  склейкам, речи; эдит в бит), `text` (кинетическая типографика), `images` (скриншоты в движении).
- QA-гейт: 15 пунктов COMMON.md + чек-лист из 20 пунктов, контактный лист, проверки по пикселям (свечение, градиент,
  мёртвые зоны, QR, видимость субтитров).
- Подписи: 5-7 названий, одно описание, закреп, TikTok, `.srt`. Обложки: 3 варианта x 2 формата, текст кодом.
- Память: `prefs.json`, напоминания о пропущенных пунктах, история роликов, выбор названий.
- Схема плана v1: только новые НЕобязательные поля относительно `viora-v8/spec/plan.schema.json`
  (`meta.fps`, `layout.top.start`, `layout.bottom.tagline/logo`, `cta.y`, `brand.fonts.logo/reason`, `brand.line_width`,
  `brand.radius`, `brand.logo`, `brand.label_style`, `brand.upper`, `brand.effects`, `captions.size/y/upper`,
  `audio.music.start/gain_db`, `audio.sfx_auto`, `fx`, `scene.duration`, `scene.transcript`,
  `source.in/out/crop_x/keep_audio/viewport/mode/images/focus/zoom_on_click`, `metadata.topic/hashtags/cover_text/utm`).
  Старые планы валидны (тест `test_original_contract_example_still_validates`).
