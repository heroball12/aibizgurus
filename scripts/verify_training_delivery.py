"""Check final video, audio, captions, chapters, timing and integrity without provider calls."""

import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path
import av, imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from align_training_module import normalize

p = argparse.ArgumentParser()
p.add_argument("--module", type=int, required=True)
args = p.parse_args()
assert 1 <= args.module <= 16
w = ROOT / f".local-artifacts/module-{args.module:02d}-v1"
movie = w / f"guru-academy-module-{args.module:02d}-v1.mp4"
edit = json.loads((w / "edit.json").read_text())
package = json.loads((ROOT / f"training/content/module{args.module}.json").read_text())
expected = " ".join(s["narration"] for s in package["scenes"])
assert normalize(" ".join(c["text"] for c in edit["captions"])) == normalize(expected)
assert all(0 <= c["start"] < c["end"] <= edit["duration"] for c in edit["captions"])
assert all(
    a["end"] <= b["start"] for a, b in zip(edit["captions"], edit["captions"][1:])
)
for c in edit["chapters"]:
    for pause in c["pauses"]:
        assert not any(
            x["start"] < pause["end"] and x["end"] > pause["start"] + 0.2
            for x in c["captions"]
        )
with av.open(str(movie)) as container:
    video = container.streams.video[0]
    audio = container.streams.audio[0]
    assert (video.width, video.height) == (1920, 1080)
    assert video.codec_context.name == "h264" and audio.codec_context.name == "aac"
    assert float(video.average_rate) == 30
    assert video.frames == round(edit["duration"] * 30)
    assert abs(float(video.duration * video.time_base) - edit["duration"]) < 1 / 30
    assert abs(float(audio.duration * audio.time_base) - edit["duration"]) < 0.05
    assert len(container.streams.subtitles) == 1
    report = {
        "duration_seconds": edit["duration"],
        "video_frames": video.frames,
        "video": "1920x1080 H.264 30 fps",
        "audio": "AAC 48000 Hz",
        "caption_cues": len(edit["captions"]),
        "caption_minimum_seconds": round(
            min(c["end"] - c["start"] for c in edit["captions"]), 3
        ),
        "caption_last_end": edit["captions"][-1]["end"],
        "chapters": len(edit["chapters"]),
        "word_count": len(expected.split()),
    }
ff = imageio_ffmpeg.get_ffmpeg_exe()
r = subprocess.run(
    [
        ff,
        "-v",
        "error",
        "-i",
        str(movie),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-f",
        "null",
        "-",
    ],
    capture_output=True,
    text=True,
    check=True,
)
assert not r.stderr.strip(), r.stderr
report["full_decode"] = "passed"
print("Complete audio/video decode passed.", flush=True)
r = subprocess.run(
    [ff, "-v", "error", "-i", str(movie), "-f", "ffmetadata", "-"],
    capture_output=True,
    text=True,
    check=True,
)
assert r.stdout.count("[CHAPTER]") == len(edit["chapters"])
(w / "delivery-metadata.txt").write_text(r.stdout)
r = subprocess.run(
    [
        ff,
        "-hide_banner",
        "-nostats",
        "-i",
        str(movie),
        "-vn",
        "-sn",
        "-dn",
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ],
    capture_output=True,
    text=True,
    check=True,
)
(w / "loudness-check.txt").write_text(r.stderr)
levels = json.JSONDecoder().raw_decode(r.stderr[r.stderr.rfind("{") :])[0]
report["encoded_loudness_lufs"] = float(levels["input_i"])
report["encoded_true_peak_dbtp"] = float(levels["input_tp"])
assert -18 <= report["encoded_loudness_lufs"] <= -14
assert report["encoded_true_peak_dbtp"] < 0
report["bytes"] = movie.stat().st_size
report["sha256"] = hashlib.file_digest(movie.open("rb"), "sha256").hexdigest()
report["source_sha256"] = hashlib.sha256(
    (ROOT / f"training/content/module{args.module}.json").read_bytes()
).hexdigest()
# Fast start: locate top-level boxes rather than searching compressed payload bytes.
boxes = []
with movie.open("rb") as f:
    offset = 0
    while offset < report["bytes"]:
        f.seek(offset)
        header = f.read(16)
        size = int.from_bytes(header[:4], "big")
        kind = header[4:8].decode("ascii")
        if size == 1:
            size = int.from_bytes(header[8:16], "big")
        if size == 0:
            size = report["bytes"] - offset
        assert size >= 8
        boxes.append(kind)
        offset += size
assert boxes.index("moov") < boxes.index("mdat")
report["fast_start"] = True
report["limits"] = [
    "Owner continuous viewing/listening and final series acceptance pending",
    "Private production hosting and playback acceptance pending",
    "Generation checks do not publish content or award certification",
]
report["module_number"] = args.module
(w / "qa-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
