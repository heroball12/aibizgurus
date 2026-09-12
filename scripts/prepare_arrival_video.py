"""Create the web delivery from a reviewed Runway master.

Build-only dependency: imageio-ffmpeg (already used for the demo film).
Usage: python scripts/prepare_arrival_video.py /path/to/reviewed-master.mp4
The original master is preserved. The website serves only the completed export.
"""
import argparse
from pathlib import Path
import subprocess

import imageio_ffmpeg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    destination = root / "static/video/ai-arrival.mp4"
    temporary = destination.with_name("ai-arrival.building.mp4")
    if source in (destination, temporary):
        parser.error("Use the reviewed master as input, not the delivery file.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
            "-vf", "scale='trunc(min(1920,iw)/2)*2':-2,fps=24",
            "-c:v", "libx264", "-preset", "slow", "-crf", "24",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-af", "loudnorm=I=-18:TP=-1.5:LRA=11", "-ar", "48000",
            "-movflags", "+faststart", str(temporary),
        ], check=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Ready: {destination} ({destination.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
