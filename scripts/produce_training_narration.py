"""Workstation-only, resumable narration production for the approved first module.

Each submission is recorded before the paid request. Existing request records are
never resubmitted, including uncertain failures. No automatic paid retries. Keys
come from Django settings; only non-secret receipts go into the ignored workdir.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AVATAR = "b6494a17-6106-4592-9e52-e6685a76e830"


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "submit", "status", "download"])
    parser.add_argument("--scenes", type=int, nargs="+")
    parser.add_argument(
        "--workdir", type=Path, default=ROOT / ".local-artifacts/module-01-v1"
    )
    args = parser.parse_args()
    work = args.workdir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = ROOT / "training/content/module1.json"
    data = json.loads(source.read_text())
    scenes = args.scenes or list(range(1, len(data["scenes"]) + 1))
    assert all(1 <= n <= 14 for n in scenes)
    if args.action == "prepare":
        package = (ROOT / "docs/training/MODULE_01_PACKAGE.md").read_text()
        for n, scene in enumerate(data["scenes"], 1):
            script = scene["narration"].strip()
            assert script in package, f"Scene {n} differs from owner-reviewed package"
            folder = work / f"scene-{n:02d}"
            folder.mkdir(exist_ok=True)
            destination = folder / "narration.txt"
            if destination.exists():
                if destination.read_text() != script + "\n":
                    assert not (
                        folder / "request.json"
                    ).exists(), f"Scene {n} already submitted; preserve take and create a revision"
                    assert not (
                        folder / "reuse.json"
                    ).exists(), (
                        f"Scene {n} reuses approved media; review revised script"
                    )
                    destination.write_text(script + "\n")
            else:
                destination.write_text(script + "\n")
        write(
            work / "source-manifest.json",
            {
                "source": str(source.relative_to(ROOT)),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "authorization": "2026-09-27: perfect lets do the rest; approved pilot, full first lesson next",
                "avatar_id": AVATAR,
                "voice": "runway-live-preset/vincent",
                "new_requests": 13,
                "developer_credit_estimate": 26,
                "scope": "Full Module 1 only; scene 1 reuses accepted pilot narration",
            },
        )
        print("Prepared 14 exact narration scripts; 13 require new generation.")
        return

    if args.action in {"submit", "status"}:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django

        django.setup()
        from assistant_ai.concierge import runway_request

    if args.action == "submit":
        if len(scenes) > 3:
            raise SystemExit("Submit at most three scenes, then inspect status/cost.")
        avatar = runway_request("GET", "/avatars/" + AVATAR)
        assert avatar["voice"]["presetId"] == "vincent"
        assert avatar["voice"]["type"] == "runway-live-preset"
        for n in scenes:
            if n == 1:
                raise SystemExit(
                    "Scene 1 reuses approved pilot audio; do not regenerate."
                )
            folder = work / f"scene-{n:02d}"
            if (folder / "request.json").exists():
                print(f"Scene {n}: existing request; no resubmission.", flush=True)
                continue
            org = runway_request("GET", "/organization")
            if org["creditBalance"] < 10:
                raise SystemExit(
                    "Narration credits low; notify owner before continuing."
                )
            payload = {
                "model": "gwm1_avatars",
                "avatar": {"type": "custom", "avatarId": AVATAR},
                "speech": {
                    "type": "text",
                    "text": (folder / "narration.txt").read_text().strip(),
                },
            }
            write(
                folder / "request.json",
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "voice": avatar["voice"],
                    "credits_before": org["creditBalance"],
                    "payload": payload,
                },
            )
            receipt = runway_request("POST", "/avatar_videos", payload)
            write(folder / "receipt.json", receipt)
            print(f"Scene {n}: submitted {receipt['id']}", flush=True)
    elif args.action == "status":
        for n in scenes:
            folder = work / f"scene-{n:02d}"
            if not (folder / "receipt.json").exists():
                continue
            task_id = json.loads((folder / "receipt.json").read_text())["id"]
            result = runway_request("GET", "/tasks/" + task_id)
            write(folder / "result.json", result)
            print(
                json.dumps(
                    {"scene": n, **{k: v for k, v in result.items() if k != "output"}}
                ),
                flush=True,
            )
            cost = result.get("cost", result.get("estimatedCost", {})).get("credits", 0)
            if cost > 4:
                raise SystemExit(
                    "Provider cost changed materially; review before further submissions."
                )
        org = runway_request("GET", "/organization")
        write(
            work / "latest-billing.json",
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "credits": org["creditBalance"],
            },
        )
    else:
        import imageio_ffmpeg

        for n in scenes:
            folder = work / f"scene-{n:02d}"
            if (folder / "narration.wav").exists():
                continue
            if not (folder / "result.json").exists():
                continue
            result = json.loads((folder / "result.json").read_text())
            if result["status"] != "SUCCEEDED":
                continue
            assert len(result["output"]) == 1
            url = result["output"][0]
            assert url.startswith("https://")
            target = folder / "voice-source.mp4"
            partial = folder / "voice-source.partial"
            if not target.exists():
                with urlopen(url, timeout=30) as response, partial.open("wb") as out:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
                partial.replace(target)
            subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(target),
                    "-vn",
                    "-c:a",
                    "pcm_s16le",
                    str(folder / "narration.wav"),
                ],
                check=True,
            )
            print(f"Scene {n}: downloaded and audio extracted.", flush=True)


if __name__ == "__main__":
    main()
