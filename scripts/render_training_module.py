"""Render the approved Module 1 lesson from aligned narration and reviewed footage.

Workstation dependencies: Pillow, numpy, imageio-ffmpeg. No generation calls,
database writes or publication. --previews exports representative visual beats.
"""

import argparse
import json
import math
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import render_training_pilot as art

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS = art.W, art.H, art.FPS
PURPLE, GOLD, WHITE, MUTED = art.PURPLE, art.GOLD, art.WHITE, art.MUTED
FFMPEG = art.FFMPEG


def heading(draw, title, y=210, size=56, width=1700):
    return art.paragraph(draw, (90, y), title, width, size, WHITE, 1.12, True)


def frame_chrome(img, chapter, local, total):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, 51, 109, 90), 10, fill="#3F225F", outline=PURPLE, width=2)
    d.polygon([(89, 59), (99, 72), (89, 82), (79, 72)], fill=GOLD)
    art.txt(d, (125, 54), "AI BUSINESS GURUS", 27, WHITE, True)
    art.txt(d, (125, 86), "A C A D E M Y", 16, MUTED)
    label = f'{chapter.get("module_number", 1):02d}  /  {chapter.get("module_label", "THE SDR MISSION")}'
    label_size = 24
    while d.textlength(label, font=art.font(label_size, True)) > 850:
        label_size -= 1
    art.txt(
        d,
        (1850 - d.textlength(label, font=art.font(label_size, True)), 62),
        label,
        label_size,
        MUTED,
        True,
    )
    d.line((70, 133, 1850, 133), fill="#4C335D")
    d.line((70, 1013, 1850, 1013), fill="#382844", width=3)
    d.line(
        (70, 1013, 70 + 1780 * (chapter["start"] + local) / total, 1013),
        fill=PURPLE,
        width=3,
    )
    count = chapter.get("chapter_count", 14)
    for index in range(1, count):
        x = 70 + 1780 * index / count
        d.line((x, 1010, x, 1016), fill="#735187", width=1)
    label = f'{chapter["number"]:02d} / {count}  ·  {chapter["title"]}'
    art.txt(d, (70, 1032), label, 19, MUTED)
    art.txt(d, (1590, 1032), "FULL LESSON / REVIEW", 16, MUTED)


def card(
    draw, bounds, label, body, active=True, index=None, body_size=34, accent=PURPLE
):
    x, y, x1, y1 = bounds
    draw.rounded_rectangle(
        bounds,
        23,
        fill="#251735" if active else "#181021",
        outline=accent if active else "#493356",
        width=2,
    )
    top = y + 29
    if index is not None:
        art.txt(draw, (x + 28, top), f"{index:02d}", 23, GOLD, True)
        top += 43
    label_height = art.paragraph(
        draw,
        (x + 28, top),
        label,
        x1 - x - 56,
        29,
        GOLD if active else MUTED,
        1.1,
        True,
    )
    top += max(56, label_height + 18)
    for line in body.splitlines():
        top += (
            art.paragraph(
                draw,
                (x + 28, top),
                line,
                x1 - x - 56,
                body_size,
                WHITE if active else MUTED,
                1.28,
            )
            + 12
        )


@lru_cache(maxsize=8)
def capture_image(workdir, kind):
    work = Path(workdir)
    if kind in {"demo-modes", "demo-guided"}:
        source = ROOT / ".local-artifacts/module-10-v1"
        filename, crop, limits = {
            "demo-modes": ("demo-home.png", (328, 367, 1256, 525), (1700, 440)),
            "demo-guided": ("demo-guided.png", (747, 165, 1255, 522), (1000, 450)),
        }[kind]
        img = Image.open(source / filename).convert("RGB").crop(crop)
        ratio = min(limits[0] / img.width, limits[1] / img.height)
        return img.resize(
            (round(img.width * ratio), round(img.height * ratio)),
            Image.Resampling.LANCZOS,
        )
    if kind in {"finder", "sheet", "sheet-save"}:
        source = ROOT / ".local-artifacts/module-05-v1"
        filename, crop = {
            "finder": ("crm-finder.png", (265, 285, 1240, 513)),
            "sheet": ("crm-sheet.png", (254, 311, 1238, 558)),
            "sheet-save": ("crm-sheet.png", (254, 151, 1240, 283)),
        }[kind]
        img = Image.open(source / filename).convert("RGB").crop(crop)
        ratio = min(1700 / img.width, 440 / img.height)
        return img.resize(
            (round(img.width * ratio), round(img.height * ratio)),
            Image.Resampling.LANCZOS,
        )
    if kind == "booking":
        img = (
            Image.open(work / "crm-booking.png")
            .convert("RGB")
            .crop((272, 105, 812, 535))
        )
    else:
        img = (
            Image.open(work / "crm-handoff.png")
            .convert("RGB")
            .crop((274, 166, 809, 397))
        )
    ratio = min(1000 / img.width, 450 / img.height)
    return img.resize(
        (round(img.width * ratio), round(img.height * ratio)), Image.Resampling.LANCZOS
    )


def board_frame(base, board, elapsed, span, work):
    img = base.copy()
    d = ImageDraw.Draw(img)
    items = board["items"]
    kind = board["kind"]
    accent = "#E995A4" if board.get("tone") == "bad" else PURPLE
    art.txt(
        d,
        (94, 165),
        "WORKED EXAMPLE" if board.get("fictional") else "LEARN THE PRINCIPLE",
        19,
        GOLD,
        True,
    )
    title_h = heading(d, board["title"])
    top = max(365, 230 + title_h + 40)
    if board.get("fictional"):
        art.txt(d, (1510, 167), "FICTIONAL BUSINESS", 17, MUTED, True)
    reveal_window = max(1, min(12, span * 0.65))
    active_index = min(
        len(items) - 1, int(max(0, elapsed) / reveal_window * len(items))
    )
    if kind in {"cards", "choices", "meeting"}:
        count = len(items)
        gap = 26
        width = (1740 - gap * (count - 1)) / count
        for i, (label, body) in enumerate(items):
            x = 90 + i * (width + gap)
            active = i <= active_index
            card(
                d,
                (x, top, x + width, 820),
                label,
                body,
                active,
                None if kind == "choices" else i + 1,
                34 if count < 4 else 31,
                accent,
            )
            if active:
                f = art.ease((elapsed - i * reveal_window / count) / 0.5)
                d.line(
                    (x + 28, 788, x + 28 + (width - 56) * f, 788), fill=accent, width=4
                )
    elif kind == "flow":
        count = len(items)
        gap = 38
        width = (1740 - gap * (count - 1)) / count
        for i, (label, body) in enumerate(items):
            x = 90 + i * (width + gap)
            card(
                d,
                (x, top + 45, x + width, 805),
                label,
                body,
                i <= active_index,
                i + 1,
                31 if count < 5 else 29,
            )
            if i < count - 1:
                y = top + 240
                progress = art.ease((elapsed - (i + 1) * reveal_window / count) / 0.6)
                d.line(
                    (x + width + 3, y, x + width + 3 + (gap - 6) * progress, y),
                    fill=GOLD,
                    width=4,
                )
                if progress > 0.9:
                    d.polygon(
                        [
                            (x + width + gap - 3, y),
                            (x + width + gap - 14, y - 8),
                            (x + width + gap - 14, y + 8),
                        ],
                        fill=GOLD,
                    )
    elif kind in {"compare", "focus"}:
        width = (1740 - 36 * (len(items) - 1)) / len(items)
        for i, (label, body) in enumerate(items):
            x = 90 + i * (width + 36)
            card(d, (x, top, x + width, 825), label, body, True, None, 40, accent)
        if len(items) == 2:
            art.txt(d, (920, top - 42), "→", 34, GOLD, True)
    elif kind == "quote":
        d.rounded_rectangle(
            (90, top, 1830, 840), 27, fill="#231431", outline=accent, width=2
        )
        art.txt(d, (133, top + 30), items[0][0], 23, GOLD, True)
        art.paragraph(d, (133, top + 102), items[0][1], 1620, 46, WHITE, 1.3, True)
        d.line(
            (133, 806, 133 + 1560 * art.ease(elapsed / 1.5), 806), fill=accent, width=4
        )
    elif kind == "dialogue":
        gap = 18
        height = min(170, (510 - gap * (len(items) - 1)) / len(items))
        for i, (label, body) in enumerate(items):
            x = 90 if i % 2 == 0 else 220
            y = top + i * (height + gap)
            active = i <= active_index
            d.rounded_rectangle(
                (x, y, x + 1605, y + height),
                20,
                fill="#251735" if active else "#181021",
                outline=accent if active else "#493356",
                width=2,
            )
            art.txt(d, (x + 26, y + 19), label, 21, GOLD, True)
            art.paragraph(
                d, (x + 26, y + 58), body, 1545, 33, WHITE if active else MUTED, 1.17
            )
    elif kind == "qualification":
        for i, (label, body) in enumerate(items):
            x = 90 + (i % 4) * 443
            y = top + (i // 4) * 230
            card(d, (x, y, x + 414, y + 209), label, body, i <= active_index, None, 28)
    elif kind == "workspace":
        picture = capture_image(str(work), board["capture"])
        d.rounded_rectangle(
            (90, top, 1830, top + 458), 22, fill="#100C17", outline="#745088", width=2
        )
        img.paste(
            picture,
            (110 + (1700 - picture.width) // 2, top + 9 + (440 - picture.height) // 2),
        )
        art.txt(
            d,
            (100, top + 478),
            board.get(
                "capture_caption",
                "REAL CRM CAPTURE  /  ISOLATED PRACTICE WORKSPACE  /  NO CUSTOMER OUTREACH",
            ),
            18,
            GOLD,
            True,
        )
    elif kind == "crm":
        picture = capture_image(str(work), board["capture"])
        d.rounded_rectangle(
            (90, top, 1130, top + 465), 22, fill="#140E20", outline="#745088", width=2
        )
        img.paste(
            picture,
            (110 + (1000 - picture.width) // 2, top + 7 + (450 - picture.height) // 2),
        )
        for i, (label, body) in enumerate(items):
            card(
                d,
                (1160, top + i * 237, 1830, top + i * 237 + 222),
                label,
                body,
                True,
                None,
                32,
            )
        art.txt(
            d,
            (100, top + 479),
            board.get(
                "capture_caption",
                "REAL CRM CAPTURE  /  SYNTHETIC RECORD  /  NO INVITATION SENT",
            ),
            18,
            GOLD,
            True,
        )
    elif kind == "recap":
        for i, (label, body) in enumerate(items):
            y = top + i * 95
            active = i <= active_index
            d.rounded_rectangle(
                (90, y, 1830, y + 80),
                15,
                fill="#251735" if active else "#181021",
                outline=PURPLE if active else "#493356",
            )
            art.txt(d, (120, y + 21), label, 26, GOLD, True)
            art.txt(d, (198, y + 19), body, 32, WHITE if active else MUTED, True)
    else:
        raise ValueError(f"Unknown board kind: {kind}")
    return img


def board_state(board, elapsed, span):
    """Reuse unchanged teaching frames while preserving every animation frame."""
    kind, count = board["kind"], len(board["items"])
    window = max(1, min(12, span * 0.65))
    active = min(count - 1, int(max(0, elapsed) / window * count))
    if kind in {"cards", "choices", "meeting"}:
        return active, tuple(
            art.ease((elapsed - i * window / count) / 0.5) for i in range(active + 1)
        )
    if kind == "flow":
        return active, tuple(
            art.ease((elapsed - (i + 1) * window / count) / 0.6)
            for i in range(count - 1)
        )
    if kind == "quote":
        return art.ease(elapsed / 1.5)
    if kind in {"dialogue", "qualification", "recap"}:
        return active
    return None


def pause_frame(base, pause, t):
    img = base.copy()
    d = ImageDraw.Draw(img)
    art.txt(d, (93, 175), "YOUR TURN / PRACTICE", 22, GOLD, True)
    heading(d, "Pause. Think. Try it out loud.", 235, 60)
    art.paragraph(d, (95, 365), pause["prompt"], 1200, 44, WHITE, 1.35, True)
    remaining = max(0, math.ceil(pause["end"] - t))
    d.ellipse((1450, 355, 1790, 695), fill="#241435", outline=PURPLE, width=4)
    value = str(remaining)
    width = d.textlength(value, font=art.font(116, True))
    art.txt(d, (1620 - width / 2, 445), value, 116, WHITE, True)
    fraction = (t - pause["start"]) / (pause["end"] - pause["start"])
    d.arc((1438, 343, 1802, 707), -90, -90 + 360 * fraction, fill=GOLD, width=8)
    art.txt(
        d,
        (95, 790),
        "Need longer? Pause the video and continue when you're ready.",
        31,
        MUTED,
    )
    return img


def instructor(frame, chapter, amplitude):
    img = art.light_response(frame, amplitude)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(150):
        d.line((0, y, W, y), fill=(8, 5, 15, int(215 * (1 - y / 150))))
    for y in range(690, H):
        d.line((0, y, W, y), fill=(8, 5, 15, int(220 * (y - 690) / (H - 690))))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(img)
    art.txt(d, (85, 709), f'GURU / CHAPTER {chapter["number"]:02d}', 21, GOLD, True)
    art.paragraph(d, (82, 750), chapter["title"], 1720, 45, WHITE, 1.1, True)
    return img


def render_chapter(work, chapter, total, previews=False):
    folder = work / f'scene-{chapter["number"]:02d}'
    with wave.open(str(folder / "edited.wav")) as f:
        rate = f.getframerate()
        samples = (
            np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(float)
            / 32768
        )
    frames = round(chapter["duration"] * FPS)
    padded = np.pad(samples, (0, frames * (rate // FPS) - len(samples)))
    rms = np.sqrt(np.mean(padded.reshape(frames, rate // FPS) ** 2, axis=1))
    amps = np.convolve(np.minimum(1, rms / 0.13), [0.15, 0.25, 0.35, 0.25], mode="same")
    base = art.base_image()
    body = art.decode_shot(work / f'shot-{chapter["shot"]}.mp4')
    preview_at = {0, 3 * FPS, frames - 1}
    for i, board in enumerate(chapter["boards"]):
        end = (
            chapter["boards"][i + 1]["start"]
            if i + 1 < len(chapter["boards"])
            else chapter["duration"]
        )
        preview_at.add(
            min(
                frames - 1,
                round(
                    max(10.1, board["start"] + min(4, (end - board["start"]) * 0.5))
                    * FPS
                ),
            )
        )
    for pause in chapter["pauses"]:
        preview_at.add(round((pause["start"] + 2) * FPS))
    out = None
    if not previews:
        out = subprocess.Popen(
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
                str(folder / "picture.mp4"),
            ],
            stdin=subprocess.PIPE,
        )
    last_board_key, last_board_frame = None, None
    try:
        for i in range(frames):
            t = i / FPS
            body_frame = next(body) if i < 300 else None
            if previews and i not in preview_at:
                continue
            pause = next(
                (p for p in chapter["pauses"] if p["start"] <= t < p["end"]), None
            )
            if pause:
                img = pause_frame(base, pause, t)
            elif body_frame is not None:
                img = instructor(body_frame, chapter, amps[i])
            else:
                index = max(
                    j for j, b in enumerate(chapter["boards"]) if b["start"] <= t
                )
                board = chapter["boards"][index]
                end = (
                    chapter["boards"][index + 1]["start"]
                    if index + 1 < len(chapter["boards"])
                    else chapter["duration"]
                )
                elapsed, span = t - board["start"], end - board["start"]
                key = (index, board_state(board, elapsed, span))
                if key != last_board_key:
                    last_board_frame = board_frame(base, board, elapsed, span, work)
                    last_board_key = key
                img = last_board_frame.copy()
            frame_chrome(img, chapter, t, total)
            if not pause:
                art.add_caption(img, t, chapter["captions"])
            if i in preview_at:
                img.save(folder / f"frame-{i:04d}.jpg", quality=93)
            if out:
                out.stdin.write(img.tobytes())
    finally:
        body.close()
        if out:
            out.stdin.close()
            if out.wait():
                raise RuntimeError("Chapter encoding failed")
    print(
        f'Chapter {chapter["number"]:02d}: {chapter["duration"]:.2f}s {"previews" if previews else "rendered"}',
        flush=True,
    )


def mux(work, edit):
    listing = work / "picture-files.txt"
    listing.write_text(
        "\n".join(
            f"file '{(work/f'scene-{c["number"]:02d}/picture.mp4').as_posix()}'"
            for c in edit["chapters"]
        )
        + "\n"
    )
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(work / "picture-master.mp4"),
        ],
        check=True,
    )
    metadata = [
        ";FFMETADATA1",
        "title=" + edit["title"],
        "artist=AI Business Gurus",
    ]
    for c in edit["chapters"]:
        metadata.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f'START={round(c["start"]*1000)}',
                f'END={round((c["start"]+c["duration"])*1000)}',
                "title=" + c["title"],
            ]
        )
    (work / "chapters.ffmeta").write_text("\n".join(metadata) + "\n")
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-i",
            str(work / "picture-master.mp4"),
            "-i",
            str(work / "narration-master.wav"),
            "-i",
            str(work / "chapters.ffmeta"),
            "-i",
            str(work / "captions.vtt"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "3:s:0",
            "-map_metadata",
            "2",
            "-map_chapters",
            "2",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=eng",
            "-t",
            str(edit["duration"]),
            "-movflags",
            "+faststart",
            str(
                work / f'guru-academy-module-{edit.get("module_number", 1):02d}-v1.mp4'
            ),
        ],
        check=True,
    )
    print("Finished full lesson export.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir", type=Path, default=ROOT / ".local-artifacts/module-01-v1"
    )
    parser.add_argument("--scenes", type=int, nargs="+")
    parser.add_argument("--previews", action="store_true")
    parser.add_argument("--mux-only", action="store_true")
    args = parser.parse_args()
    work = args.workdir.resolve()
    edit = json.loads((work / "edit.json").read_text())
    if not args.mux_only:
        for c in edit["chapters"]:
            if args.scenes and c["number"] not in args.scenes:
                continue
            render_chapter(work, c, edit["duration"], args.previews)
    if not args.previews and (args.mux_only or not args.scenes):
        mux(work, edit)


if __name__ == "__main__":
    main()
