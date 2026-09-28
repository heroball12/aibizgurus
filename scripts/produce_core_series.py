"""Resume the owner-authorized Core SDR narration batch without duplicate charges.

The approved nine-shot instructor library is reused. Only exact per-chapter
scripts are sent to the existing Vincent avatar. No content is published.
An uncertain POST or failed take requires human inspection; it is never retried.
"""

import argparse, hashlib, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
AVATAR = "b6494a17-6106-4592-9e52-e6685a76e830"
STATE = ROOT / ".local-artifacts/core-series-v1"


def write(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def emit(message):
    print(datetime.now().strftime("%H:%M:%S"), message, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--modules", nargs="+", type=int, default=list(range(2, 17)))
    p.add_argument("--credit-cap", type=int, default=450)
    p.add_argument("--follow", action="store_true")
    args = p.parse_args()
    assert all(2 <= n <= 16 for n in args.modules)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from assistant_ai.concierge import runway_request
    import imageio_ffmpeg
    from faster_whisper import WhisperModel
    from align_training_module import align

    STATE.mkdir(exist_ok=True, parents=True)
    avatar = runway_request("GET", "/avatars/" + AVATAR)
    assert (
        avatar["voice"]["type"] == "runway-live-preset"
        and avatar["voice"]["presetId"] == "vincent"
    )
    model = None
    last_message = ""
    last_poll = {}
    blocked = set()
    while True:
        scenes = []
        missing = []
        for number in args.modules:
            source = ROOT / f"training/content/module{number}.json"
            if not source.exists():
                missing.append(number)
                continue
            try:
                package = json.loads(source.read_text())
            except json.JSONDecodeError:
                missing.append(number)
                continue
            work = ROOT / f".local-artifacts/module-{number:02d}-v1"
            work.mkdir(exist_ok=True)
            manifest = dict(
                module=number,
                source=str(source.relative_to(ROOT)),
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                voice="runway-live-preset/vincent",
                avatar_id=AVATAR,
                authorization="Full Module 1 accepted; remaining Core SDR series approved 2026-09-27",
                scope="Generation only; no publication",
            )
            old = work / "source-manifest.json"
            if (
                old.exists()
                and json.loads(old.read_text())["sha256"] != manifest["sha256"]
            ):
                raise RuntimeError(
                    f"Module {number} source changed after preparation; preserve original takes and explicitly revise."
                )
            if not old.exists():
                write(old, manifest)
            for asset in list(
                (ROOT / ".local-artifacts/module-01-v1").glob("shot-?.mp4")
            ) + list((ROOT / ".local-artifacts/module-01-v1").glob("crm-*.png")):
                target = work / asset.name
                if not target.exists():
                    target.symlink_to(asset)
            for index, scene in enumerate(package["scenes"], 1):
                folder = work / f"scene-{index:02d}"
                folder.mkdir(exist_ok=True)
                narration = folder / "narration.txt"
                text = scene["narration"].strip()
                if narration.exists():
                    assert (
                        narration.read_text() == text + "\n"
                    ), f"Script changed in {folder}"
                else:
                    narration.write_text(text + "\n")
                scenes.append((number, index, folder, scene))
        cost = 0
        reserved = 0
        # Reserve the repair requests too: the 450-credit ceiling covers the
        # whole remaining series, not just this worker's base narration.
        repair_reserved = sum(
            2
            for pattern in (
                "module-*/scene-*/retake-*/request.json",
                "module-*/scene-*/repair-*/request.json",
            )
            for _ in (ROOT / ".local-artifacts").glob(pattern)
        )
        active = []
        new = []
        transcribe = []
        for number, index, folder, scene in scenes:
            result = (
                json.loads((folder / "result.json").read_text())
                if (folder / "result.json").exists()
                else {}
            )
            receipt = (
                json.loads((folder / "receipt.json").read_text())
                if (folder / "receipt.json").exists()
                else {}
            )
            if result.get("cost", {}).get("credits", 0) > 4:
                raise RuntimeError(
                    "Provider cost changed materially; inspect before proceeding."
                )
            cost += result.get("cost", {}).get("credits", 0)
            if (folder / "request.json").exists() and not receipt:
                raise RuntimeError(
                    f"Uncertain paid request at {folder}; inspect provider before any retry."
                )
            if receipt and result.get("status") not in {
                "SUCCEEDED",
                "FAILED",
                "CANCELED",
            }:
                active.append((number, index, folder, scene, receipt))
                reserved += 2
            elif not receipt:
                new.append((number, index, folder, scene))
            elif (
                result.get("status") == "SUCCEEDED"
                and not (folder / "transcript.json").exists()
            ):
                transcribe.append((number, index, folder, scene, result))
            elif result.get("status") in {"FAILED", "CANCELED"}:
                blocked.add(f'{number:02d}.{index:02d}: provider {result["status"]}')
        if cost + reserved + repair_reserved > args.credit_cap:
            raise RuntimeError("Authorized batch credit cap reached.")
        for number, index, folder, scene in new[: max(0, 3 - len(active))]:
            if cost + reserved + repair_reserved + 2 > args.credit_cap:
                raise RuntimeError("Authorized batch credit cap reached.")
            org = runway_request("GET", "/organization")
            write(
                STATE / "latest-billing.json",
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "credits": org["creditBalance"],
                    "task_cost_so_far": cost,
                },
            )
            if org["creditBalance"] < 10:
                raise RuntimeError("Runway developer credits low; notify owner.")
            payload = {
                "model": "gwm1_avatars",
                "avatar": {"type": "custom", "avatarId": AVATAR},
                "speech": {"type": "text", "text": scene["narration"].strip()},
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
            reserved += 2
            active.append((number, index, folder, scene, receipt))
            emit(f'M{number:02d} chapter {index:02d}: submitted {receipt["id"]}')
        for number, index, folder, scene, receipt in active:
            if time.monotonic() - last_poll.get(receipt["id"], 0) < 20:
                continue
            result = runway_request("GET", "/tasks/" + receipt["id"])
            write(folder / "result.json", result)
            last_poll[receipt["id"]] = time.monotonic()
            if result["status"] in {"SUCCEEDED", "FAILED", "CANCELED"}:
                emit(
                    f'M{number:02d} chapter {index:02d}: {result["status"]}; reported cost {result.get("cost",{}).get("credits","pending")}'
                )
        # One completed take per pass keeps queue/status checks responsive.
        if transcribe:
            number, index, folder, scene, result = transcribe[0]
            if not (folder / "narration.wav").exists():
                target = folder / "voice-source.mp4"
                if not target.exists():
                    # Generation links expire. A resumed run refreshes the
                    # existing task, without submitting or paying for it again.
                    receipt = json.loads((folder / "receipt.json").read_text())
                    result = runway_request("GET", "/tasks/" + receipt["id"])
                    write(folder / "result.json", result)
                    assert len(result["output"]) == 1 and result["output"][
                        0
                    ].startswith("https://")
                    with urlopen(result["output"][0], timeout=60) as response, (
                        folder / "voice-source.partial"
                    ).open("wb") as out:
                        while chunk := response.read(1024 * 1024):
                            out.write(chunk)
                    (folder / "voice-source.partial").replace(target)
                subprocess.run(
                    [
                        imageio_ffmpeg.get_ffmpeg_exe(),
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(target),
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "48000",
                        "-c:a",
                        "pcm_s16le",
                        str(folder / "narration.partial.wav"),
                    ],
                    check=True,
                )
                (folder / "narration.partial.wav").replace(folder / "narration.wav")
            if model is None:
                model = WhisperModel(
                    "small.en",
                    device="cpu",
                    compute_type="int8",
                    download_root=str(
                        ROOT / ".local-artifacts/training-pilot-v1/models"
                    ),
                    local_files_only=True,
                )
            segments, _ = model.transcribe(
                str(folder / "narration.wav"),
                language="en",
                word_timestamps=True,
                beam_size=5,
                vad_filter=False,
            )
            recognized = [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "words": [
                        {
                            "start": x.start,
                            "end": x.end,
                            "word": x.word,
                            "probability": x.probability,
                        }
                        for x in s.words
                    ],
                }
                for s in segments
            ]
            write(folder / "transcript.json", recognized)
            try:
                align(scene["narration"], recognized)
            except ValueError as e:
                write(folder / "review-needed.json", {"differences": str(e)})
                emit(f"M{number:02d} chapter {index:02d}: transcription review needed")
            else:
                emit(f"M{number:02d} chapter {index:02d}: exact words verified")
        pending = sum(not (f / "transcript.json").exists() for _, _, f, _ in scenes)
        summary = f"{len(scenes)-pending}/{len(scenes)} chapters transcribed; {cost} developer credits; missing content {missing}; blocked {sorted(blocked)}"
        if summary != last_message:
            write(
                STATE / "progress.json",
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "chapters": len(scenes),
                    "transcribed": len(scenes) - pending,
                    "credits": cost,
                    "missing_modules": missing,
                    "blocked": sorted(blocked),
                },
            )
            last_message = summary
        if not pending and (not missing or not args.follow):
            emit("All currently available requested chapters have been transcribed.")
            return
        time.sleep(1 if transcribe else 10)


if __name__ == "__main__":
    main()
