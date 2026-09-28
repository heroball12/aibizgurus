"""Package all 16 verified films for private Render disk playback; never publishes."""

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def clock(seconds):
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "deliverables/Guru-Core-SDR-Academy"
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(
            "Delivery folder already exists; preserve it and choose a new --output."
        )

    # Validate the entire series before creating a folder that looks complete.
    prepared = []
    for number in range(1, 17):
        work = ROOT / f".local-artifacts/module-{number:02d}-v1"
        source = ROOT / f"training/content/module{number}.json"
        movie = work / f"guru-academy-module-{number:02d}-v1.mp4"
        qa = json.loads((work / "qa-report.json").read_text())
        edit = json.loads((work / "edit.json").read_text())
        package = json.loads(source.read_text())
        assert qa["full_decode"] == "passed" and qa["fast_start"]
        assert qa["bytes"] == movie.stat().st_size and qa["sha256"] == digest(movie)
        assert qa["source_sha256"] == digest(source)
        assert abs(qa["duration_seconds"] - edit["duration"]) < 0.05
        assert len(edit["chapters"]) == len(package["scenes"])
        assert -18 <= qa["encoded_loudness_lufs"] <= -14
        assert qa["encoded_true_peak_dbtp"] < 0
        for name in ["captions.vtt", "transcript.txt", "scene-01/frame-0090.jpg"]:
            assert (work / name).is_file(), (number, name)
        prepared.append((number, work, source, movie, qa, edit, package))

    staging = output.with_name(output.name + ".building")
    if staging.exists():
        raise SystemExit(
            "An unfinished package exists; inspect it before choosing a new output."
        )
    staging.mkdir(parents=True)
    entries = []
    ledger = []

    def record(path):
        return {
            "path": path.relative_to(staging).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }

    def copy(source, destination):
        shutil.copyfile(source, destination)
        return record(destination)

    for number, work, source, movie, qa, edit, package in prepared:
        slug = re.sub(
            r"[^a-z0-9]+", "-", package.get("short_title", "The SDR Mission").lower()
        ).strip("-")
        folder = staging / f"{number:02d}-{slug}-{qa['sha256'][:12]}"
        folder.mkdir()
        content = copy(source, folder / "lesson.json")
        evidence = copy(work / "qa-report.json", folder / "technical-qa.json")
        assets = {
            "video": copy(movie, folder / f"{number:02d}-Guru-{slug}.mp4"),
            "captions": copy(work / "captions.vtt", folder / "English-captions.vtt"),
            "poster": copy(work / "scene-01/frame-0090.jpg", folder / "poster.jpg"),
        }
        supporting = [copy(work / "transcript.txt", folder / "Transcript.txt")]
        guide = folder / "Field-guide.md"
        guide.write_text(f"# {package['title']}\n\n{package['job_aid']}\n")
        supporting.append(record(guide))
        quiz = folder / "Manager-quiz-and-practice.json"
        write_json(
            quiz,
            {
                "audience": "Owner/manager review; includes answers. Keep this folder private.",
                "questions": package["questions"],
                "scenario": package["scenario"],
            },
        )
        supporting.append(record(quiz))
        for name in ["transcription-review.json", "delivery-examples.json"]:
            if (work / name).is_file():
                supporting.append(copy(work / name, folder / name))
        narration_review = []
        for index, scene in enumerate(package["scenes"], 1):
            chapter = work / f"scene-{index:02d}"
            decisions = {}
            for name in (
                "retake-applied.json",
                "repair-applied.json",
                "boundary-review.json",
            ):
                if (chapter / name).is_file():
                    decisions[name] = json.loads((chapter / name).read_text())
            narration_review.append(
                {"chapter": index, "title": scene["title"], "decisions": decisions}
            )
        review_file = folder / "Narration-review.json"
        write_json(
            review_file,
            {
                "method": "Script-to-recognition comparison, independent recognition of flagged passages, documented spelling/boundary review and exact recorded corrections. Not continuous human listening.",
                "chapters": narration_review,
            },
        )
        supporting.append(record(review_file))
        chapters = [
            {
                "title": c["title"],
                "start": c["start"],
                "end": c["start"] + c["duration"],
            }
            for c in edit["chapters"]
        ]
        entries.append(
            {
                "number": number,
                "title": package["title"],
                "duration_seconds": edit["duration"],
                "chapters": chapters,
                "content": content,
                "qa": evidence,
                "assets": assets,
                "supporting_files": supporting,
                "review_status": (
                    "Film accepted by owner"
                    if number == 1
                    else "Ready for owner review"
                ),
            }
        )
        for result_file in sorted(work.glob("scene-*/**/result.json")):
            result = json.loads(result_file.read_text())
            receipt_file = result_file.with_name("receipt.json")
            receipt = (
                json.loads(receipt_file.read_text()) if receipt_file.exists() else {}
            )
            # Deliberately exclude signed URLs, request headers and credentials.
            ledger.append(
                {
                    "module": number,
                    "source": result_file.relative_to(work).as_posix(),
                    "task_id": result.get("id", receipt.get("id")),
                    "status": result.get("status"),
                    "cost": result.get("cost", {}),
                    "use": "Production source; originals and rejected takes preserved in workstation archive",
                }
            )
    write_json(
        staging / "manifest.json",
        {
            "format": "aibg-core-academy-1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "policy_version": "2026-09-27",
            "modules": entries,
        },
    )
    write_json(
        staging / "Production-ledger.json",
        {
            "scope": "Saved chapter narration task results, including original and correction takes. A successful task is not necessarily the take used in the final film.",
            "motion_library": "Nine previously accepted Guru shots reused. Historical pilot and motion-generation charges are recorded separately in docs/training/RUNWAY_PRODUCTION_LOG.md in the repository.",
            "records": ledger,
        },
    )
    shutil.copyfile(
        ROOT / "docs/training/RENDER_DELIVERY.md", staging / "Render-setup.md"
    )
    total = sum(e["duration_seconds"] for e in entries)
    rows = "\n".join(
        f"| {e['number']:02d} | [{e['title']}]({e['assets']['video']['path']}) | {clock(e['duration_seconds'])} |"
        for e in entries
    )
    (staging / "START-HERE.md").write_text(
        "# Guru Core SDR Academy\n\n"
        f"16 complete films • {int(total // 3600)} hours {round(total % 3600 / 60)} minutes total. "
        "1920×1080 MP4 with Guru’s existing Vincent voice, visible violet speech light, "
        "captions, chapters and practice pauses. The approved Module 1 film is unchanged.\n\n"
        "| Lesson | Video | Runtime |\n| --- | --- | --- |\n" + rows + "\n\n"
        "Each folder includes the video, English captions, transcript, field guide, "
        "quiz/answer key, practice scenario, source lesson and technical QA. "
        "The manager files contain answers: keep this entire folder private.\n\n"
        "## Put it on the site\n\n"
        "Follow [Render setup](Render-setup.md). Upload the complete folder, preserving "
        "its names, then run the verification/import commands against the matching deployed code. "
        "Do not upload it to public static storage or commit the media to Git.\n\n"
        "## Review and release\n\n"
        "Module 1 was accepted by the owner. The remaining films are ready for owner "
        "review; importing does not publish them or award employee progress. Technical checks "
        "cover full video/audio decoding, duration, chapters, caption timing, loudness and hashes. "
        "They are not a claim of continuous human listening. Review the lessons in the Academy, "
        "mark their assets reviewed and use the owner approval/publication controls. "
        "Advanced and industry tracks remain later phases.\n\n"
        "Pricing throughout is custom to the recommended build. Only qualified human AI "
        "Specialists discuss pricing, only during a Growth Assessment.\n"
    )
    files = sorted(p for p in staging.rglob("*") if p.is_file())
    (staging / "SHA256SUMS.txt").write_text(
        "".join(f"{digest(p)}  {p.relative_to(staging).as_posix()}\n" for p in files)
    )
    staging.rename(output)
    print(
        json.dumps(
            {"folder": str(output), "films": len(entries), "duration_seconds": total},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
