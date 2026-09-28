"""Render and measure every teaching board before final video assembly."""

import argparse, json, sys
from pathlib import Path
from PIL import Image, ImageDraw
import render_training_module as video

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--modules", type=int, nargs="+", default=list(range(1, 17)))
args = p.parse_args()
output = ROOT / ".local-artifacts/core-series-v1/layouts"
output.mkdir(parents=True, exist_ok=True)
original_paragraph = video.art.paragraph
original_card = video.card
scope = []
issues = []
context = {}


def paragraph(
    draw, xy, text, width, size=32, color=video.MUTED, leading=1.35, bold=False
):
    height = original_paragraph(draw, xy, text, width, size, color, leading, bold)
    bottom = (
        scope[-1][3] - 25 if scope else (795 if context.get("kind") == "quote" else 890)
    )
    if xy[1] + height > bottom:
        issues.append(
            {
                **context,
                "text": text,
                "bottom": round(xy[1] + height, 1),
                "limit": bottom,
            }
        )
    return height


def card(draw, bounds, *a, **kw):
    scope.append(bounds)
    try:
        return original_card(draw, bounds, *a, **kw)
    finally:
        scope.pop()


video.art.paragraph = paragraph
video.card = card
base = video.art.base_image()
count = 0
for number in args.modules:
    plans = json.loads(
        (ROOT / f"training/content/module{number}_visuals.json").read_text()
    )
    files = []
    for chapter, plan in enumerate(plans, 1):
        for i, board in enumerate(plan["boards"], 1):
            context.update(module=number, chapter=chapter, board=i, kind=board["kind"])
            img = video.board_frame(
                base, board, 99, 100, ROOT / f".local-artifacts/module-{number:02d}-v1"
            )
            f = output / f"m{number:02d}-c{chapter:02d}-b{i:02d}.jpg"
            img.save(f, quality=90)
            files.append(f)
            count += 1
    # One contact sheet per 12 boards. Full-resolution board images remain available.
    for page, start in enumerate(range(0, len(files), 12), 1):
        group = files[start : start + 12]
        sheet = Image.new("RGB", (1920, 360 * ((len(group) + 2) // 3)), "#100919")
        draw = ImageDraw.Draw(sheet)
        for i, f in enumerate(group):
            sheet.paste(
                Image.open(f).resize((640, 360)), ((i % 3) * 640, (i // 3) * 360)
            )
            draw.text(((i % 3) * 640 + 10, (i // 3) * 360 + 5), f.stem, fill="white")
        sheet.save(output / f"module-{number:02d}-contact-{page:02d}.jpg", quality=92)
report = {"boards_rendered": count, "modules": args.modules, "text_overflows": issues}
(output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
if issues:
    sys.exit(1)
