#!/usr/bin/env python3
"""plan.json -> вертикальный шортс 1080x1920: геймплей сверху, запись сайтов в центре, реклама снизу.

python make_short.py plan.json out_dir
Нужно: playwright, edge-tts, ffmpeg, google-chrome.
"""
import asyncio, json, math, re, subprocess, sys, time
from pathlib import Path
import edge_tts
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
CHROME = "/usr/local/bin/google-chrome"
W, H = 1080, 1920
GAME_H, SITE_H, AD_H = 600, 720, 600
SITE_Y, AD_Y = GAME_H, GAME_H + SITE_H
PAD = 0.35  # пауза после каждой реплики

CURSOR_JS = """
(()=>{let el;const mk=()=>{el=document.createElement('div');el.style.cssText='position:fixed;z-index:2147483647;pointer-events:none;width:34px;height:34px;left:-50px;top:0;transition:transform .08s';
el.innerHTML='<svg width="34" height="34" viewBox="0 0 24 24"><path d="M3 2l7 19 3-8 8-3z" fill="#fff" stroke="#000" stroke-width="1.6" stroke-linejoin="round"/></svg>';document.documentElement.appendChild(el)};
addEventListener('mousemove',e=>{if(!el)mk();el.style.left=e.clientX-4+'px';el.style.top=e.clientY-2+'px'},true);
addEventListener('mousedown',e=>{if(!el)mk();const r=document.createElement('div');r.style.cssText=`position:fixed;z-index:2147483646;pointer-events:none;left:${e.clientX-30}px;top:${e.clientY-30}px;width:60px;height:60px;border-radius:50%;border:4px solid #ff4d6d;transition:all .45s;opacity:.9`;document.documentElement.appendChild(r);requestAnimationFrame(()=>{r.style.transform='scale(1.8)';r.style.opacity='0'});setTimeout(()=>r.remove(),600)},true)})();
"""


def sh(*a, **k):
    subprocess.run([str(x) for x in a], check=True, **k)


def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out)


async def tts(scene, out, voice, speed):
    """Озвучка одной реплики. Возвращает (длительность, [(слово, начало, конец)])."""
    raw = out.with_suffix(".raw.mp3")
    for attempt in range(6):  # сервис иногда отвечает пустотой
        words, audio = [], b""
        try:
            async for ch in edge_tts.Communicate(scene["say"], voice, boundary="WordBoundary").stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    s = ch["offset"] / 1e7 / speed
                    words.append((ch["text"], s, s + ch["duration"] / 1e7 / speed))
            break
        except edge_tts.exceptions.NoAudioReceived:
            await asyncio.sleep(4)
    else:
        raise RuntimeError("озвучка не получилась")
    raw.write_bytes(audio)
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-filter:a", f"atempo={speed}", "-ar", 44100, "-ac", 1, out)
    return dur(out), words


async def record_scene(browser, scene, seconds, out_dir, idx):
    ctx = await browser.new_context(viewport={"width": W, "height": SITE_H}, record_video_dir=str(out_dir / f"rec{idx}"),
                                    record_video_size={"width": W, "height": SITE_H}, locale="en-US")
    await ctx.add_init_script(CURSOR_JS)
    page = await ctx.new_page()
    t_ctx = time.monotonic()
    t0 = None
    for a in scene["actions"]:
        if t0 is not None:
            wait = t0 + a.get("t", 0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        d = a["do"]
        if d == "goto":
            await page.goto(a["url"], wait_until="load")
            await page.wait_for_timeout(a.get("settle", 1200))
            await page.mouse.move(*a.get("from", (760, 520)))
            t0 = time.monotonic()
        elif d == "move":
            await page.mouse.move(a["x"], a["y"], steps=a.get("steps", 25))
        elif d in ("click", "hover"):
            loc = page.get_by_text(a["text"], exact=a.get("exact", True)).first if "text" in a else page.locator(a["sel"]).first
            box = await loc.bounding_box()
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=a.get("steps", 25))
            if d == "click":
                await page.mouse.down(); await page.mouse.up()
        elif d == "type":
            await page.locator(a["sel"]).first.click()
            await page.keyboard.type(a["text"], delay=a.get("delay", 90))
        elif d == "press":
            await page.keyboard.press(a["key"])
        elif d == "scroll":
            await page.mouse.move(*a.get("at", (600, 400)), steps=10)
            n = a.get("steps", 20)
            for _ in range(n):
                await page.mouse.wheel(0, a["dy"] / n)
                await page.wait_for_timeout(35)
    wait = t0 + seconds - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    path = await page.video.path()
    await ctx.close()
    return Path(path), t0 - t_ctx


def render_game(total, out):
    async def go():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            pg = await b.new_page(viewport={"width": W, "height": GAME_H})
            await pg.goto((HERE / "assets/game.html").as_uri())
            ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", "30", "-i", "-",
                                   "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
            for _ in range(int(total * 30) + 5):
                await pg.evaluate("frame(1/30)")
                ff.stdin.write(await pg.screenshot(type="jpeg", quality=92))
            ff.stdin.close(); ff.wait()
            await b.close()
    asyncio.run(go())


def shot_html(html, out, w, h):
    async def go():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            pg = await b.new_page(viewport={"width": w, "height": h})
            await pg.goto((HERE / html).as_uri()); await pg.wait_for_timeout(300)
            await pg.screenshot(path=str(out)); await b.close()
    asyncio.run(go())


def ts(x):
    return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


def chunks(words, subs, say):
    """Слова -> короткие субтитры (до 3 слов, до 20 знаков), с заменой произношения на написание."""
    toks = say.split()
    punct = [t[-1] in ",.!?:;" for t in toks] if len(toks) == len(words) else [False] * len(words)
    out, cur = [], []
    for (w, s, e), end in zip(words, punct):
        shown = subs.get(w.strip(",.!?"), w.strip(",.!?"))
        if shown and cur and (len(cur) >= 3 or len(" ".join(x[0] for x in cur)) + len(shown) > 20):
            out.append(cur); cur = []
        if shown:
            cur.append((shown, s, e))
        if end and cur:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def build_ass(scenes_info, subs, out):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,DejaVu Sans,66,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,8,2,2,40,40,0,1
Style: Badge,DejaVu Sans,54,&H00FFFFFF,&H000000FF,&H00FF5C7C,&H00FF5C7C,1,0,0,0,100,100,0,0,3,16,0,8,40,40,0,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    ev = []
    for sc in scenes_info:
        if sc.get("badge"):
            ev.append(f"Dialogue: 1,{ts(sc['start'])},{ts(sc['start'] + sc['len'])},Badge,,0,0,0,,{{\\pos(540,{SITE_Y + 22})}}{sc['badge']}")
        cs = chunks(sc["words"], subs, sc["say"])
        for i, c in enumerate(cs):
            s = sc["start"] + c[0][1]
            e = sc["start"] + (cs[i + 1][0][1] if i + 1 < len(cs) else c[-1][2] + 0.3)
            ev.append(f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\an2\\pos(540,{AD_Y - 40})}}{' '.join(x[0] for x in c)}")
    out.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def main():
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[2]); out_dir.mkdir(parents=True, exist_ok=True)
    speed = plan.get("speed", 1.06)

    infos, t = [], 0.0
    for i, sc in enumerate(plan["scenes"]):
        d, words = asyncio.run(tts(sc, out_dir / f"v{i}.wav", plan["voice"], speed))
        L = d + PAD
        infos.append({**sc, "start": t, "len": L, "words": words, "audio": out_dir / f"v{i}.wav", "adur": d})
        t += L
    total = t
    print(f"озвучка: {total:.1f} c")

    async def rec_all():
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            res = [await record_scene(b, sc, sc["len"], out_dir, i) for i, sc in enumerate(infos)]
            await b.close()
            return res
    recs = asyncio.run(rec_all())

    parts = []
    for i, (sc, (vid, trim)) in enumerate(zip(infos, recs)):
        o = out_dir / f"s{i}.mp4"
        sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{trim:.2f}", "-t", f"{sc['len']:.2f}", "-i", vid,
           "-vf", f"fps=30,scale={W}:{SITE_H},setsar=1", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", o)
        parts.append(o)
    (out_dir / "list.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", out_dir / "list.txt", "-c", "copy", out_dir / "center.mp4")

    ain = []
    for sc in infos:
        ain += ["-i", sc["audio"]]
    n = len(infos)
    af = "".join(f"[{k}:a]apad=whole_dur={sc['len']:.3f}[a{k}];" for k, sc in enumerate(infos)) + "".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    sh("ffmpeg", "-y", "-loglevel", "error", *ain, "-filter_complex", af, "-map", "[aout]", out_dir / "voice.wav")

    render_game(total, out_dir / "game.mp4")
    shot_html("assets/ad.html", out_dir / "ad.png", W, AD_H)
    build_ass(infos, plan.get("subs", {}), out_dir / "caps.ass")

    final = out_dir / f"{plan['name']}.mp4"
    fc = (f"color=c=0x07070d:s={W}x{H}:r=30:d={total:.2f}[bg];"
          f"[bg][0:v]overlay=0:0[a];[a][1:v]overlay=0:{SITE_Y}[b];[b][2:v]overlay=0:{AD_Y}[c];"
          f"[c]subtitles={out_dir / 'caps.ass'}:fontsdir=/usr/share/fonts/truetype/dejavu[v]")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", out_dir / "game.mp4", "-i", out_dir / "center.mp4", "-loop", "1", "-framerate", "30", "-i", out_dir / "ad.png",
       "-i", out_dir / "voice.wav", "-filter_complex", fc, "-map", "[v]", "-map", "3:a", "-t", f"{total:.2f}",
       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", final)
    print("готово:", final, f"{dur(final):.1f} c")


if __name__ == "__main__":
    main()
