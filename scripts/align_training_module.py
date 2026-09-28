"""Verify and align full Module 1 narration locally; never calls a paid provider.

Preserves raw ASR and original audio. Numeric spellings, acronyms and contractions
are normalized explicitly. Any other word discrepancy stops final assembly.
"""

import argparse
import difflib
import json
import math
import re
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "here's": ["here", "is"],
    "that's": ["that", "is"],
    "it's": ["it", "is"],
    "we're": ["we", "are"],
    "you're": ["you", "are"],
    "they're": ["they", "are"],
    "don't": ["do", "not"],
    "doesn't": ["does", "not"],
    "isn't": ["is", "not"],
    "can't": ["can", "not"],
    "cannot": ["can", "not"],
    "i'm": ["i", "am"],
    "let's": ["let", "us"],
    "we'll": ["we", "will"],
    "i'd": ["i", "would"],
    "we'd": ["we", "would"],
    "aibg": ["a", "i", "b", "g"],
    "sdr": ["s", "d", "r"],
    "crm": ["c", "r", "m"],
    "roi": ["r", "o", "i"],
    "ai": ["a", "i"],
    "api": ["a", "p", "i"],
    "csv": ["c", "s", "v"],
    "xlsx": ["x", "l", "s", "x"],
    "lead's": ["leads"],
    "roleplay": ["role", "play"],
    "handoff": ["hand", "off"],
    "handoffs": ["hand", "offs"],
    "callback": ["call", "back"],
    "callbacks": ["call", "backs"],
    "tradeoff": ["trade", "off"],
    "tradeoffs": ["trade", "offs"],
    "overexcited": ["over", "excited"],
    "overpromised": ["over", "promised"],
    "overpromising": ["over", "promising"],
    "acknowledgement": ["acknowledgment"],
    "timezone": ["time", "zone"],
    "checkbox": ["check", "box"],
    "northstar": ["north", "star"],
    "cancelled": ["canceled"],
    "15": ["fifteen"],
    "20": ["twenty"],
    "1": ["one"],
    "2": ["two"],
    "3": ["three"],
}
_UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
for _number in range(100):
    ALIASES[str(_number)] = (
        [_UNITS[_number]]
        if _number < 20
        else [_TENS[_number // 10]] + ([_UNITS[_number % 10]] if _number % 10 else [])
    )
PAUSES = {
    6: [("Use your own words.", 15, "Say your next question out loud.")],
    13: [
        (
            "Pause and say it out loud.",
            12,
            "Ask one useful follow-up question. Explain why.",
        ),
        ("is still pending.", 25, "Write three lines: fact, hypothesis, next step."),
    ],
}


def normalize(text, aliases=None):
    table = {**ALIASES, **(aliases or {})}
    tokens = re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))
    return [part for token in tokens for part in table.get(token, [token])]


def stamp(t):
    ms = round(t * 1000)
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms%1000:03d}"


def locate(aligned, phrase, end=False):
    wanted = normalize(phrase)
    tokens, owners = [], []
    for index, word in enumerate(aligned):
        bits = normalize(word["text"])
        tokens.extend(bits)
        owners.extend([index] * len(bits))
    for i in range(len(tokens) - len(wanted) + 1):
        if tokens[i : i + len(wanted)] == wanted:
            return (
                aligned[owners[i + len(wanted) - 1]]["end"]
                if end
                else aligned[owners[i]]["start"]
            )
    raise ValueError(f"Cannot align visual/practice phrase: {phrase}")


def align(script, segments, aliases=None):
    expected = normalize(script)
    actual = normalize(" ".join(s["text"] for s in segments), aliases)
    if actual != expected:
        differences = [
            {"expected": expected[a:b], "recognized": actual[c:d]}
            for tag, a, b, c, d in difflib.SequenceMatcher(
                a=expected, b=actual
            ).get_opcodes()
            if tag != "equal"
        ]
        raise ValueError(json.dumps(differences))
    timed = []
    for segment in segments:
        for word in segment["words"]:
            parts = normalize(word["word"], aliases)
            for i, part in enumerate(parts):
                span = (word["end"] - word["start"]) / len(parts)
                timed.append(
                    (part, word["start"] + i * span, word["start"] + (i + 1) * span)
                )
    if [x[0] for x in timed] != expected:
        raise ValueError("Word timestamps disagree with recognized segment text.")
    aligned, cursor = [], 0
    for text in script.split():
        count = len(normalize(text))
        aligned.append(
            {
                "text": text,
                "start": timed[cursor][1],
                "end": timed[cursor + count - 1][2],
            }
        )
        cursor += count
    return aligned


def captions(words):
    cues, pending = [], []
    for word in words:
        pending.append(word)
        text = " ".join(w["text"] for w in pending)
        if (
            word["text"].endswith((".", "?", "!"))
            or len(text) >= 62
            or (word["text"].endswith((",", ":")) and len(text) > 32)
        ):
            cues.append(
                {
                    "text": text,
                    "start": pending[0]["start"],
                    "end": pending[-1]["end"] + 0.16,
                }
            )
            pending = []
    if pending:
        cues.append(
            {
                "text": " ".join(w["text"] for w in pending),
                "start": pending[0]["start"],
                "end": pending[-1]["end"] + 0.16,
            }
        )
    # Keep short sentence endings with their preceding thought, rather than
    # flashing an isolated word for a fraction of a second.
    readable = []
    for cue in cues:
        if (
            readable
            and cue["end"] - cue["start"] < 0.85
            and len(cue["text"]) <= 18
            and cue["start"] - readable[-1]["end"] < 0.75
            and len(readable[-1]["text"]) + len(cue["text"]) < 110
        ):
            readable[-1]["text"] += " " + cue["text"]
            readable[-1]["end"] = cue["end"]
        else:
            readable.append(cue)
    cues = readable
    for left, right in zip(cues, cues[1:]):
        left["end"] = min(left["end"], right["start"])
    return cues


def save_wav(path, samples, rate):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(samples.astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=int, default=1)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    work = (
        args.workdir or ROOT / f".local-artifacts/module-{args.module:02d}-v1"
    ).resolve()
    package = json.loads(
        (ROOT / f"training/content/module{args.module}.json").read_text()
    )
    visuals = json.loads(
        (ROOT / f"training/content/module{args.module}_visuals.json").read_text()
    )
    if len(package["scenes"]) != len(visuals):
        raise ValueError("Every chapter requires a visual plan.")
    reviews = (
        json.loads((work / "transcription-review.json").read_text())
        if (work / "transcription-review.json").exists()
        else {}
    )
    chapters, all_cues, master, offset, errors = [], [], [], 0, []
    for n, (scene, visual) in enumerate(zip(package["scenes"], visuals), 1):
        folder = work / f"scene-{n:02d}"
        if not (folder / "transcript.json").exists():
            errors.append(f"Scene {n}: transcript pending")
            continue
        try:
            words = align(
                scene["narration"],
                json.loads((folder / "transcript.json").read_text()),
                reviews.get(str(n), {}).get("aliases"),
            )
            print(
                f"Scene {n}: approved words verified ({len(words)} words).", flush=True
            )
        except ValueError as e:
            errors.append(f"Scene {n}: {e}")
            continue
        if args.check_only:
            continue
        with wave.open(str(folder / "narration.wav")) as f:
            assert f.getnchannels() == 1 and f.getsampwidth() == 2
            rate = f.getframerate()
            assert rate == 48000
            source = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
        pauses, chunks, cursor, inserted = [], [], 0, 0
        practice = scene.get("pauses", PAUSES.get(n, []) if args.module == 1 else [])
        for phrase, seconds, prompt in practice:
            end = locate(words, phrase, end=True)
            following = next(
                (w["start"] for w in words if w["start"] >= end), end + 0.3
            )
            boundary = end + min(0.15, (following - end) / 2)
            # Insert silence between phrases, never over an actual spoken word.
            assert not any(w["start"] < boundary < w["end"] for w in words)
            point = round(boundary * rate)
            chunks.extend(
                [source[cursor:point], np.zeros(round(seconds * rate), dtype="<i2")]
            )
            pauses.append(
                {
                    "source_time": boundary,
                    "start": boundary + inserted,
                    "end": boundary + inserted + seconds,
                    "prompt": prompt,
                }
            )
            cursor = point
            inserted += seconds
        chunks.append(source[cursor:])
        speech = np.concatenate(chunks)
        duration = math.ceil((len(speech) / rate + 0.65) * 30) / 30
        if n == len(package["scenes"]):
            duration += 3
        speech = np.pad(speech, (0, round(duration * rate) - len(speech)))
        for word in words:
            word["start"] += sum(
                p["end"] - p["start"]
                for p in pauses
                if p["source_time"] <= word["start"]
            )
            word["end"] += sum(
                p["end"] - p["start"] for p in pauses if p["source_time"] < word["end"]
            )
        cues = captions(words)
        boards = [
            {**board, "start": locate(words, board["phrase"]) if board["phrase"] else 0}
            for board in visual["boards"]
        ]
        if any(a["start"] >= b["start"] for a, b in zip(boards, boards[1:])):
            raise ValueError(f"Scene {n}: visual beats must be chronological")
        chapter = {
            "module_number": args.module,
            "module_label": package.get("short_title", "THE SDR MISSION"),
            "chapter_count": len(package["scenes"]),
            "number": n,
            "title": scene["title"],
            "start": offset,
            "duration": duration,
            "shot": visual["shot"],
            "boards": boards,
            "pauses": pauses,
            "words": words,
            "captions": cues,
        }
        (folder / "aligned.json").write_text(
            json.dumps(chapter, indent=2, ensure_ascii=False)
        )
        save_wav(folder / "edited.wav", speech, rate)
        all_cues.extend(
            {**c, "start": c["start"] + offset, "end": c["end"] + offset} for c in cues
        )
        chapters.append(chapter)
        master.append(speech)
        offset += duration
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    if args.check_only:
        return
    save_wav(work / "narration-master.wav", np.concatenate(master), 48000)
    manifest = {
        "module_number": args.module,
        "title": package["title"],
        "policy_version": package["policy_version"],
        "duration": offset,
        "chapters": chapters,
        "captions": all_cues,
    }
    (work / "edit.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (work / "captions.vtt").write_text(
        "WEBVTT\n\n"
        + "\n\n".join(
            f'{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for c in all_cues
        )
        + "\n"
    )
    (work / "transcript.txt").write_text(
        "\n\n".join(
            f'{stamp(c["start"])} — {c["title"]}\n\n{package["scenes"][i]["narration"]}'
            for i, c in enumerate(chapters)
        )
        + "\n"
    )
    print(
        f"Aligned {len(chapters)} chapters, {len(all_cues)} captions; {offset:.3f} seconds."
    )


if __name__ == "__main__":
    main()
