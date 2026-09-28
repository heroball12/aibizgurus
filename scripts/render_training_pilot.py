"""Build the owner-review pilot from reviewed Runway footage and real CRM captures.

Build-only dependencies: Pillow, numpy, imageio-ffmpeg. No provider calls, production
database writes, or publication. Sources and outputs stay in the ignored workdir.
Usage: PYTHONPATH=.local-artifacts/training-pilot-v1/python .venv/bin/python scripts/render_training_pilot.py
"""

import argparse
import json
import math
import re
import subprocess
import textwrap
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS, DURATION = 1920, 1080, 30, 72
PURPLE, GOLD, WHITE, MUTED = "#BB8CF7", "#E9C36A", "#F6F1FC", "#BCB0CB"
SHOTS = [(0, 10, "a"), (16.6, 26.6, "b"), (51.5, 61.5, "c")]
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@lru_cache(maxsize=64)
def font(size, bold=False):
    return ImageFont.truetype(
        "/System/Library/Fonts/Supplemental/Arial" + (" Bold" if bold else "") + ".ttf",
        size,
    )


def txt(draw, xy, text, size=32, color=WHITE, bold=False):
    draw.text(xy, text, font=font(size, bold), fill=color, stroke_width=0)


def paragraph(draw, xy, text, width, size=32, color=MUTED, leading=1.35, bold=False):
    words, line, lines = text.split(), "", []
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font(size, bold)) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    for i, line in enumerate(lines):
        txt(draw, (xy[0], xy[1] + i * size * leading), line, size, color, bold)
    return len(lines) * size * leading


def ease(x):
    x = max(0, min(1, x))
    return 1 - (1 - x) ** 3


def base_image():
    yy, xx = np.mgrid[:H, :W]
    glow = np.exp(-(((xx - 1550) / 950) ** 2 + ((yy - 120) / 750) ** 2))
    pixels = np.stack([10 + 19 * glow, 8 + 9 * glow, 18 + 34 * glow], axis=-1).astype(
        "uint8"
    )
    img = Image.fromarray(pixels)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 80):
        d.line((x, 0, x, H), fill="#20162E", width=1)
    for y in range(0, H, 80):
        d.line((0, y, W, y), fill="#20162E", width=1)
    return img


def chrome(img, t, section, duration=DURATION):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, 51, 109, 90), 10, fill="#3F225F", outline=PURPLE, width=2)
    d.polygon([(89, 59), (99, 72), (89, 82), (79, 72)], fill=GOLD)
    txt(d, (125, 54), "AI BUSINESS GURUS", 27, WHITE, True)
    txt(d, (125, 86), "A C A D E M Y", 16, MUTED)
    txt(d, (1465, 63), "01  /  PROBLEM FIRST", 22, MUTED, True)
    d.line((70, 133, 1850, 133), fill="#4C335D", width=1)
    d.line((70, 1013, 1850, 1013), fill="#382844", width=3)
    d.line((70, 1013, 70 + 1780 * t / duration, 1013), fill=PURPLE, width=3)
    txt(d, (70, 1032), section.upper(), 18, MUTED)
    txt(d, (1597, 1032), "PILOT  /  OWNER REVIEW", 16, MUTED)


def normalize_words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def make_captions(work, basename="guru-academy-pilot-v1", transcript_aliases=None):
    # Explicitly reviewed recognizer contractions only; preserve the raw transcript.
    # No fuzzy matching or automatic deletion/insertion of script words.
    transcript_aliases = transcript_aliases or {}

    def recognized_words(text):
        return [
            expanded
            for token in normalize_words(text)
            for expanded in transcript_aliases.get(token, [token])
        ]

    segments = json.loads((work / "transcript.json").read_text())
    script = (ROOT / "docs/training/PILOT_NARRATION.txt").read_text().strip()
    actual = recognized_words(" ".join(s["text"] for s in segments))
    expected = normalize_words(script)
    if actual != expected:
        raise ValueError(
            "Spoken transcript differs from approved script; review before assembly."
        )
    timed = []
    for segment in segments:
        for word in segment["words"]:
            tokens = recognized_words(word["word"])
            for i, token in enumerate(tokens):
                span = (word["end"] - word["start"]) / len(tokens)
                timed.append(
                    (token, word["start"] + span * i, word["start"] + span * (i + 1))
                )
    script_words, aligned, cursor = script.split(), [], 0
    for word in script_words:
        count = len(normalize_words(word))
        aligned.append(
            {
                "text": word,
                "start": timed[cursor][1],
                "end": timed[cursor + count - 1][2],
            }
        )
        cursor += count
    cues, pending = [], []
    for word in aligned:
        pending.append(word)
        text = " ".join(w["text"] for w in pending)
        if (
            word["text"].endswith((".", "?", "!"))
            or len(text) > 60
            or (word["text"].endswith((",", ":")) and len(text) > 25)
        ):
            cues.append(
                {
                    "start": pending[0]["start"],
                    "end": pending[-1]["end"] + 0.14,
                    "text": text,
                }
            )
            pending = []
    if pending:
        cues.append(
            {
                "start": pending[0]["start"],
                "end": pending[-1]["end"] + 0.14,
                "text": " ".join(w["text"] for w in pending),
            }
        )
    joined = []
    for cue in cues:
        if (
            joined
            and len(cue["text"]) < 14
            and not joined[-1]["text"].endswith((".", "?", "!"))
        ):
            joined[-1]["text"] += " " + cue["text"]
            joined[-1]["end"] = cue["end"]
        else:
            joined.append(cue)
    cues = joined
    for i in range(len(cues) - 1):
        cues[i]["end"] = min(cues[i]["end"], cues[i + 1]["start"])

    def stamp(t):
        ms = round(t * 1000)
        return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms%1000:03d}"

    vtt = (
        "WEBVTT\n\n"
        + "\n\n".join(
            f'{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for c in cues
        )
        + "\n"
    )
    (work / f"{basename}.vtt").write_text(vtt)
    (work / "caption-cues.json").write_text(json.dumps(cues, indent=2))
    return cues


def add_caption(img, t, cues):
    cue = next((c for c in cues if c["start"] <= t < c["end"]), None)
    if not cue:
        return
    d = ImageDraw.Draw(img)
    lines = textwrap.wrap(cue["text"], width=68)
    height = len(lines) * 44 + 26
    box_width = max(d.textlength(line, font=font(34)) for line in lines) + 64
    x = (W - box_width) / 2
    d.rounded_rectangle(
        (x, 986 - height, x + box_width, 986),
        radius=13,
        fill="#09060F",
        outline="#523966",
        width=1,
    )
    for i, line in enumerate(lines):
        line_width = d.textlength(line, font=font(34))
        txt(d, ((W - line_width) / 2, 998 - height + i * 44), line, 34)


def light_response(frame, amplitude):
    """Track violet pixels in the helmet ROI; brighten their existing geometry."""
    arr = np.asarray(frame).copy()
    # Motion stays restrained. This region excludes chest light and room lighting.
    x0, x1, y0, y1 = int(W * 0.435), int(W * 0.59), int(H * 0.18), int(H * 0.32)
    crop = arr[y0:y1, x0:x1].astype(float)
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    candidates = (b > 215) & (r > 125) & (b > g * 1.15) & (r > g * 1.05)
    # Follow the horizontal strip, excluding purple forehead reflections.
    center = int(np.argmax(candidates.sum(axis=1)))
    rows = np.arange(crop.shape[0])[:, None]
    mask = (candidates & (abs(rows - center) <= 26)).astype("uint8") * 255
    # A luminance-following emission adjustment, never reshapes the visor.
    mask_img = Image.fromarray(mask).filter(ImageFilter.GaussianBlur(3))
    alpha = np.asarray(mask_img).astype(float) / 255
    crop *= 1 + alpha[:, :, None] * (-0.24 + amplitude * 0.45)
    arr[y0:y1, x0:x1] = np.clip(crop, 0, 255).astype("uint8")
    result = Image.fromarray(arr)
    # Soft halo around the exact tracked light, responsive to narration.
    halo = mask_img.filter(ImageFilter.GaussianBlur(12)).point(
        lambda p: int(p * amplitude * 0.4)
    )
    glow = Image.new("RGB", (x1 - x0, y1 - y0), "#B16CFF")
    result.paste(glow, (x0, y0), halo)
    return result


def shot_frame(frame, t, amplitude):
    img = light_response(frame, amplitude)
    # Thin edge shades keep titles readable while preserving helmet, torso and hands.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for y in range(150):
        a = int(210 * (1 - y / 150))
        d.line((0, y, W, y), fill=(8, 5, 15, a))
    for y in range(810, H):
        a = int(215 * (y - 810) / (H - 810))
        d.line((0, y, W, y), fill=(8, 5, 15, a))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    d = ImageDraw.Draw(img)
    if t < 10:
        txt(d, (85, 716), "MEET YOUR INSTRUCTOR", 20, GOLD, True)
        txt(d, (80, 746), "Guru", 68, WHITE, True)
        txt(d, (85, 825), "Your AI sales trainer", 30, MUTED)
    elif t < 27:
        d.rounded_rectangle(
            (1190, 210, 1825, 390), 24, fill="#170E22", outline="#705089", width=2
        )
        txt(d, (1220, 241), "Problem first.", 48, WHITE, True)
        txt(d, (1220, 305), "Technology second.", 40, GOLD, True)
    else:
        d.rounded_rectangle(
            (80, 220, 620, 420), 24, fill="#170E22", outline="#705089", width=2
        )
        txt(d, (110, 250), "EXAMPLE", 20, GOLD, True)
        paragraph(
            d,
            (110, 293),
            "Calls answered.\nQuotes left waiting.",
            455,
            42,
            WHITE,
            bold=True,
        )
    return img


def values_frame(base, t):
    img = base.copy()
    d = ImageDraw.Draw(img)
    txt(d, (90, 207), "Four habits. One better conversation.", 60, WHITE, True)
    txt(d, (94, 295), "What you need before your first supervised call.", 31, MUTED)
    values = [
        ("Listen", "Find the actual problem."),
        ("Ask", "Use useful questions."),
        ("Tell the truth", "Be clear about what you know."),
        ("Hand off", "Leave useful information."),
    ]
    for i, (title, desc) in enumerate(values):
        x = 90 + i * 443
        revealed = ease((t - 10 - i * 0.8) / 0.6)
        y = 430 + int((1 - revealed) * 25)
        active = t >= 10 + i * 0.8
        d.rounded_rectangle(
            (x, y, x + 410, y + 325),
            24,
            fill="#21132F" if active else "#15101E",
            outline=PURPLE if active else "#493356",
            width=2,
        )
        txt(d, (x + 28, y + 29), f"0{i+1}", 24, GOLD if active else MUTED, True)
        txt(d, (x + 28, y + 94), title, 38, WHITE if active else MUTED, True)
        paragraph(d, (x + 28, y + 161), desc, 350, 28, MUTED)
        if active:
            d.line(
                (x + 29, y + 283, x + 29 + 350 * revealed, y + 283),
                fill=PURPLE,
                width=4,
            )
    return img


def journey_frame(base, t):
    img = base.copy()
    d = ImageDraw.Draw(img)
    txt(d, (90, 205), "Start with their working day.", 62, WHITE, True)
    txt(d, (94, 293), "Customers. People. Handoffs.", 31, MUTED)
    cards = [
        ("01", "Customers", "Who did not call back?", 28.0),
        ("02", "Repetitive work", "Where is the team buried?", 31.7),
        ("03", "Disconnected handoffs", "What gets lost between systems?", 34.2),
    ]
    for i, (number, title, desc, start) in enumerate(cards):
        x = 90 + i * 596
        active = t >= start
        d.rounded_rectangle(
            (x, 435, x + 548, 755),
            25,
            fill="#251536" if active else "#15101E",
            outline=PURPLE if active else "#493356",
            width=2,
        )
        txt(d, (x + 33, 464), number, 25, GOLD, True)
        paragraph(d, (x + 33, 531), title, 480, 36, WHITE, bold=True)
        paragraph(d, (x + 33, 643), desc, 475, 28, MUTED)
        if i < 2:
            d.line((x + 549, 590, x + 590, 590), fill=GOLD, width=3)
            d.polygon([(x + 590, 590), (x + 579, 582), (x + 579, 598)], fill=GOLD)
        if active:
            f = ease((t - start) / 0.65)
            d.line((x + 34, 715, x + 34 + 475 * f, 715), fill=PURPLE, width=4)
    return img


def crm_frame(base, t, crm):
    img = base.copy()
    d = ImageDraw.Draw(img)
    txt(d, (90, 186), "Make the next conversation better.", 54, WHITE, True)
    txt(
        d, (95, 264), "SYNTHETIC CRM EXAMPLE  /  NO OUTREACH OR BOOKING", 20, GOLD, True
    )
    if t < 47:
        capture = crm[0 if t < 43 else 1]
        img.paste(capture, (90, 335))
    else:
        d.rounded_rectangle((90, 335, 1125, 891), 18, fill="#1C1228")
        txt(d, (130, 377), "HANDOFF EXAMPLE", 23, GOLD, True)
        paragraph(
            d,
            (130, 446),
            "Give the human specialist useful context.",
            895,
            48,
            WHITE,
            bold=True,
        )
        paragraph(
            d,
            (130, 612),
            "What they told you. What needs verification. The agreed next step.",
            890,
            36,
            MUTED,
        )
        d.line((130, 806, 1075, 806), fill="#694784", width=2)
        txt(d, (130, 831), "CLEAR NOTES  →  A BETTER CONVERSATION", 22, GOLD, True)
    d.rounded_rectangle((89, 334, 1126, 891), 16, outline="#684B80", width=2)
    cards = [
        ("FACT", "Calls are answered. Quote follow-up is inconsistent.", 39.0),
        ("HYPOTHESIS", "A consistent follow-up process may help.", 43.0),
        ("NEXT STEP", "Verify the workflow, records and responsible person.", 47.0),
    ]
    for i, (title, body, start) in enumerate(cards):
        x, y = 1170, 338 + i * 183
        active = t >= start
        d.rounded_rectangle(
            (x, y, 1830, y + 163),
            18,
            fill="#241532" if active else "#15101E",
            outline=PURPLE if active else "#493356",
            width=2,
        )
        txt(d, (x + 27, y + 18), title, 22, GOLD if active else MUTED, True)
        paragraph(d, (x + 27, y + 59), body, 604, 30, WHITE if active else MUTED)
    return img


def ending_frame(base, t):
    img = base.copy()
    d = ImageDraw.Draw(img)
    txt(d, (90, 205), "Explore a follow-up process.", 62, WHITE, True)
    txt(d, (95, 297), "A possible fit to verify with the human specialist.", 31, MUTED)
    labels = [
        ("Quote sent", "Start with the record."),
        ("Follow-up", "Give it an owner."),
        ("Human team", "Review and respond."),
    ]
    for i, (title, body) in enumerate(labels):
        x = 100 + i * 602
        d.rounded_rectangle(
            (x, 450, x + 525, 706), 24, fill="#241532", outline=PURPLE, width=2
        )
        txt(d, (x + 29, 484), f"0{i+1}", 24, GOLD, True)
        txt(d, (x + 29, 537), title, 39, WHITE, True)
        txt(d, (x + 29, 611), body, 28, MUTED)
        if i < 2:
            progress = ease((t - 61.5 - i * 1.7) / 1.5)
            d.line((x + 529, 576, x + 529 + 70 * progress, 576), fill=GOLD, width=4)
            if progress > 0.95:
                d.polygon([(x + 599, 576), (x + 585, 566), (x + 585, 586)], fill=GOLD)
    if t > 66:
        txt(d, (100, 798), "Follow the problem. Verify the fit.", 47, GOLD, True)
    return img


def decode_shot(path):
    proc = subprocess.Popen(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS}",
            "-t",
            "10",
            "-an",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    try:
        while True:
            data = proc.stdout.read(W * H * 3)
            if not data:
                break
            if len(data) != W * H * 3:
                raise ValueError("Incomplete decoded frame")
            yield Image.frombytes("RGB", (W, H), data)
    finally:
        proc.stdout.close()
        proc.wait()


def render(work, previews=False, edit=None):
    # New narration can retime the graphics without stretching approved footage.
    # Anchors pair the original composition time with the revised narration time.
    edit = edit or {}
    basename = edit.get("basename", "guru-academy-pilot-v1")
    audio = work / edit.get("audio", "narration-original.mp3")
    duration = float(edit.get("duration", DURATION))
    anchors = np.asarray(
        edit.get("anchors", [[0, 0], [DURATION, duration]]), dtype=float
    )
    if (
        anchors.ndim != 2
        or anchors.shape[1] != 2
        or not np.isfinite(anchors).all()
        or not np.all(np.diff(anchors, axis=0) > 0)
        or not np.array_equal(anchors[0], [0, 0])
        or not np.array_equal(anchors[-1], [DURATION, duration])
        or not 60 <= duration <= 90
    ):
        raise ValueError(
            "Edit needs increasing time anchors covering the 60–90s pilot."
        )

    def new_time(t):
        return float(np.interp(t, anchors[:, 0], anchors[:, 1]))

    shots = [(new_time(start), new_time(end), name) for start, end, name in SHOTS]
    for start, end, _ in shots:
        if abs(end - start - 10) > 1e-6:
            raise ValueError(
                "Approved character shots must remain ten seconds at natural speed."
            )
        if any(abs(t * FPS - round(t * FPS)) > 1e-6 for t in (start, end)):
            raise ValueError("Character shot boundaries must land on whole frames.")
    cues = make_captions(work, basename, edit.get("transcript_aliases"))
    raw = subprocess.check_output(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(audio),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        ]
    )
    samples = np.frombuffer(raw, dtype="<f4")
    if len(samples) / 16000 > duration or cues[-1]["end"] > duration:
        raise ValueError("The edit would truncate narration or captions.")
    frame_count = round(FPS * duration)
    amplitude = []
    for i in range(frame_count):
        block = samples[int(i / FPS * 16000) : int((i + 1) / FPS * 16000)]
        rms = float(np.sqrt(np.mean(block**2))) if len(block) else 0
        amplitude.append(min(1, rms / 0.13))
    amplitude = np.convolve(amplitude, [0.15, 0.25, 0.35, 0.25], mode="same")
    base = base_image()
    # Crop only irrelevant empty margins; all CRM pixels remain genuine captures.
    capture = Image.open(work / "crm-before.png").convert("RGB")
    crm = []
    for bounds in [(272, 150, 810, 394), (272, 410, 810, 620)]:
        crop = capture.crop(bounds)
        factor = min(1035 / crop.width, 555 / crop.height)
        crop = crop.resize(
            (round(crop.width * factor), round(crop.height * factor)),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new("RGB", (1035, 555), "#140F1E")
        canvas.paste(crop, ((1035 - crop.width) // 2, (555 - crop.height) // 2))
        crm.append(canvas)
    shot_iters = {name: decode_shot(work / f"shot-{name}.mp4") for _, _, name in SHOTS}
    output = None
    if not previews:
        output = subprocess.Popen(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{W}x{H}",
                "-r",
                str(FPS),
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(work / "picture-master.mp4"),
            ],
            stdin=subprocess.PIPE,
        )
    preview_frames = {
        0,
        90,
        210,
        360,
        525,
        720,
        870,
        1080,
        1200,
        1380,
        1500,
        1590,
        1710,
        1800,
        1920,
        2070,
        2159,
    }
    preview_frames = {
        min(frame_count - 1, round(new_time(i / FPS) * FPS)) for i in preview_frames
    }
    sections = [
        "Welcome",
        "Four habits",
        "Problem first",
        "Their working day",
        "A useful handoff",
        "Find the actual problem",
        "Verify the fit",
    ]
    try:
        for i in range(frame_count):
            t = i / FPS
            picture_t = float(np.interp(t, anchors[:, 1], anchors[:, 0]))
            shot = next(
                ((start, name) for start, end, name in shots if start <= t < end), None
            )
            if shot:
                img = shot_frame(next(shot_iters[shot[1]]), picture_t, amplitude[i])
                section = sections[{"a": 0, "b": 2, "c": 5}[shot[1]]]
            elif picture_t < 16.6:
                img = values_frame(base, picture_t)
                section = sections[1]
            elif picture_t < 38.7:
                img = journey_frame(base, picture_t)
                section = sections[3]
            elif picture_t < 51.5:
                img = crm_frame(base, picture_t, crm)
                section = sections[4]
            else:
                img = ending_frame(base, picture_t)
                section = sections[6]
            chrome(img, t, section, duration)
            add_caption(img, t, cues)
            if i in preview_frames:
                img.save(work / f"frame-{i:04d}.jpg", quality=92)
            if output:
                output.stdin.write(img.tobytes())
            if i % (FPS * 10) == 0:
                print(f"Rendered {t:.0f}/{duration:g}s", flush=True)
    finally:
        for iterator in shot_iters.values():
            iterator.close()
        if output:
            output.stdin.close()
            if output.wait():
                raise RuntimeError("Video encoding failed")
    if output:
        subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-i",
                str(work / "picture-master.mp4"),
                "-i",
                str(audio),
                "-i",
                str(work / f"{basename}.vtt"),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-map",
                "2:s:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11,apad",
                "-c:s",
                "mov_text",
                "-metadata:s:s:0",
                "language=eng",
                "-t",
                str(duration),
                "-movflags",
                "+faststart",
                str(work / f"{basename}.mp4"),
            ],
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir", type=Path, default=ROOT / ".local-artifacts/training-pilot-v1"
    )
    parser.add_argument("--previews", action="store_true")
    parser.add_argument(
        "--edit", type=Path, help="JSON with audio, basename, duration and time anchors"
    )
    args = parser.parse_args()
    render(
        args.workdir.resolve(),
        args.previews,
        json.loads(args.edit.read_text()) if args.edit else None,
    )
