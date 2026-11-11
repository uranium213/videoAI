#!/usr/bin/env python3
"""Bina video 9:16 (1080x1920) daripada audio + skrip.

Guna:  python3 build_video.py --audio audio.wav --script script.json --out video.mp4 [--duration 30]

Penanda highlight dalam skrip: [[term]]. Sempadan scene dicari automatik
daripada jeda senyap dalam audio (N ayat -> N-1 jeda terpanjang).
"""
import argparse, json, math, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
GREEN, BLUE, YELLOW, DARK = (14, 124, 58), (27, 42, 140), (255, 230, 0), (20, 24, 40)
BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


def font(p, s): return ImageFont.truetype(p, s)


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path], text=True)
    return float(out.strip())


def detect_silences(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "silencedetect=n=-35dB:d=0.15",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r)]
    sil = list(zip(starts, ends))
    merged = []
    for s, e in sil:  # gabung jeda yang rapat
        if merged and s - merged[-1][1] < 0.12:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged, (ends[0] if starts and starts[0] < 0.01 else 0.0)


def speech_bounds(sil, total):
    t0 = sil[0][1] if sil and sil[0][0] < 0.01 else 0.0
    t1 = sil[-1][0] if sil and sil[-1][1] >= total - 0.05 else total
    return t0, t1


def parse_markup(text):
    """-> list of (word, is_term)"""
    words = []
    for m in re.finditer(r"\[\[(.+?)\]\](\S*)|(\S+)", text):
        if m.group(1):
            parts = m.group(1).split()
            parts[-1] += m.group(2)  # akhiran/tanda baca melekat pada perkataan terakhir
            words.extend((w, True) for w in parts)
        else:
            words.append((m.group(3), False))
    # tanda baca yang melekat pada perkataan sebelum markup: kekal sebagai perkataan biasa
    return words


def build_timeline(scenes, sil, total):
    s0, s1 = speech_bounds(sil, total)
    inner = [x for x in sil if x[0] > s0 + 0.3 and x[1] < s1 - 0.3]
    n = len(scenes)
    lens = [sum(len(w) + 2 for w, _ in parse_markup(sc["text"])) for sc in scenes]
    picks, cum = [], 0
    for i in range(n - 1):
        cum += lens[i]
        exp = s0 + (s1 - s0) * cum / sum(lens)
        cands = [x for x in inner if abs((x[0] + x[1]) / 2 - exp) < 4.0 and (not picks or x[0] > picks[-1][1])]
        if not cands:
            sys.exit(f"Tiada jeda dekat {exp:.1f}s untuk sempadan scene {i+1}. Semak audio/skrip.")
        picks.append(min(cands, key=lambda x: abs((x[0] + x[1]) / 2 - exp) / 4.0 - (x[1] - x[0])))
    segs, prev = [], s0
    for p in picks:
        segs.append((prev, p[0])); prev = p[1]
    segs.append((prev, s1))
    bounds = [0.0] + [(a[1] + b[0]) / 2 for a, b in zip(segs[:-1], segs[1:])] + [None]
    out = []
    for i, sc in enumerate(scenes):
        ws, we = segs[i]
        words = parse_markup(sc["text"])
        wt = [len(w) + 2 for w, _ in words]
        tot, acc, timed = sum(wt), 0, []
        for (w, term), l in zip(words, wt):
            timed.append((w, term, ws + (we - ws) * acc / tot))
            acc += l
        out.append({"start": bounds[i], "speech": (ws, we), "words": timed, "color": sc.get("color", "green")})
    return out, s0, s1, picks


def gradient(c1, c2):
    top = Image.new("RGB", (1, 2), c1); top.putpixel((0, 1), c2)
    return top.resize((W, H), Image.BILINEAR)


def make_bg(color):
    base = {"green": GREEN, "blue": BLUE}[color]
    dark = tuple(int(c * 0.55) for c in base)
    return gradient(base, dark).convert("RGBA")


def layout_words(words, fnt, maxw, draw):
    lines, cur, curw = [], [], 0
    space = draw.textlength(" ", font=fnt)
    for idx, (w, term, t) in enumerate(words):
        ww = draw.textlength(w, font=fnt)
        if cur and curw + space + ww > maxw:
            lines.append(cur); cur, curw = [], 0
        cur.append((idx, w, ww)); curw += ww + (space if len(cur) > 1 else 0)
    if cur: lines.append(cur)
    return lines, space


def render_text(scene, t, local, fnt, size):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    maxw = W - 160
    lines, space = layout_words(scene["words"], fnt, maxw, d)
    lh = int(size * 1.45)
    y0 = int(H * 0.5 - len(lines) * lh / 2) + int((1 - ease(local / 0.4)) * 60)
    alpha_in = ease(local / 0.35)
    for li, line in enumerate(lines):
        lw = sum(x[2] for x in line) + space * (len(line) - 1)
        x = (W - lw) / 2
        y = y0 + li * lh
        li_words = [q[0] for q in line]
        for idx, w, ww in line:
            _, term, ts = scene["words"][idx]
            spoken = t >= ts
            if term:
                p = ease((t - ts) / 0.25) if spoken else 0
                if p > 0:
                    pad = 14
                    nxt = li_words[li_words.index(idx) + 1] if li_words.index(idx) + 1 < len(li_words) else None
                    ext = space if (nxt is not None and scene["words"][nxt][1]) else 0
                    d.rounded_rectangle((x - pad, y - 4, x - pad + (ww + 2 * pad + ext) * p, y + size + 14),
                                        radius=18, fill=YELLOW + (int(255 * alpha_in),))
                col = DARK if p > 0.6 else (255, 255, 255)
                a = 255
            else:
                col = (255, 255, 255)
                a = 255 if spoken else 90
            d.text((x, y), w, font=fnt, fill=col + (int(a * alpha_in),))
            x += ww + space
    return layer


def draw_logo(img, cx, cy, h, alpha=255):
    logo = Image.open("assets/logo.png").convert("RGBA")
    w = int(logo.width * h / logo.height)
    logo = logo.resize((w, h), Image.LANCZOS)
    if alpha < 255:
        a = logo.getchannel("A").point(lambda v: v * alpha // 255); logo.putalpha(a)
    img.alpha_composite(logo, (int(cx - w / 2), int(cy - h / 2)))


def centered(d, y, text, fnt, fill):
    d.text(((W - d.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=fill)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True); ap.add_argument("--script", required=True)
    ap.add_argument("--out", default="video.mp4"); ap.add_argument("--duration", type=float, default=0)
    a = ap.parse_args()
    cfg = json.load(open(a.script))
    atotal = probe_duration(a.audio)
    sil, _ = detect_silences(a.audio)
    scenes, s0, s1, picks = build_timeline(cfg["scenes"], sil, atotal)
    dur = a.duration or (s1 + 2.5)
    if s1 > dur - 1.2:
        print(f"AMARAN: audio bercakap sampai {s1:.1f}s, video {dur:.1f}s - outro terlalu pendek", file=sys.stderr)
    print("Sempadan scene:", [round(s["start"], 2) for s in scenes], "| speech", round(s0, 2), "-", round(s1, 2), "| video", round(dur, 2))
    outro_start = s1 + 0.3
    bgs = {c: make_bg(c) for c in ("green", "blue")}
    size = 76
    fnt, fsm = font(BOLD, size), font(BOLD, 40)
    fhead, ffoot = font(BOLD, 44), font(BOLD, 54)
    head = cfg.get("header", "Panitia Pendidikan Islam"); sub = cfg.get("subheader", "SK Taman Selasih")
    credit = cfg.get("credit", "Pesanan daripada Panitia Pendidikan Islam")

    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", a.audio,
                           "-af", f"apad=whole_dur={dur}", "-t", str(dur),
                           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "160k", a.out], stdin=subprocess.PIPE)
    nframes = int(dur * FPS)
    for f in range(nframes):
        t = f / FPS
        idx = max(i for i, s in enumerate(scenes) if t >= s["start"])
        sc = scenes[idx]
        local = t - sc["start"]
        img = bgs[sc["color"]].copy()
        if idx > 0 and local < 0.4:  # crossfade latar
            prev = bgs[scenes[idx - 1]["color"]].copy()
            img = Image.blend(prev, img, ease(local / 0.4))
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        # selingan: bulatan bergerak perlahan
        for k in range(4):
            r = 180 + 70 * k
            cx = W * (0.2 + 0.2 * k) + 90 * math.sin(t * 0.6 + k * 1.7)
            cy = H * (0.25 + 0.17 * k) + 120 * math.cos(t * 0.5 + k)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 14))
        # jalur kuning (warna logo)
        d.rectangle((0, 0, W, 14), fill=YELLOW + (255,))
        d.rectangle((0, H - 14, W, H), fill=YELLOW + (255,))

        img.alpha_composite(ov)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        if t < outro_start:
            draw_logo(img, W / 2, 190, 250)
            centered(d, 345, head.upper(), fhead, YELLOW + (255,))
            centered(d, 400, sub.upper(), fsm, (255, 255, 255, 235))
            # progress bar
            p = min(1, t / max(0.1, outro_start))
            d.rounded_rectangle((90, H - 120, W - 90, H - 106), radius=7, fill=(255, 255, 255, 60))
            d.rounded_rectangle((90, H - 120, 90 + (W - 180) * p, H - 106), radius=7, fill=YELLOW + (255,))
        else:
            o = t - outro_start
            k = ease(o / 0.5)
            draw_logo(img, W / 2, 760, int(560 * (0.8 + 0.2 * k)), int(255 * k))
            if k > 0:
                al = int(255 * k)
                centered(d, 1110, credit, font(BOLD, 44), (255, 255, 255, al))
                centered(d, 1175, sub.upper() if False else "SK TAMAN SELASIH", font(BOLD, 72), YELLOW + (al,))
                centered(d, 1300, "Keyakinan Teras Kecemerlangan", font(REG, 42), (255, 255, 255, al))
        img.alpha_composite(ov)
        if t < outro_start:
            img.alpha_composite(render_text(sc, t, local, fnt, size))
        ff.stdin.write(img.convert("RGB").tobytes())
    ff.stdin.close(); ff.wait()
    print("Siap:", a.out)


if __name__ == "__main__":
    main()
