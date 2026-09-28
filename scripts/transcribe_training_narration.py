"""Create word timestamps for reviewed English training narration, entirely locally.

Build-only dependency: faster-whisper. The model downloads on first use; no audio
is uploaded. Use the approved script as a separate verification source, never as
the recognizer's prompt. The renderer rejects unreviewed word discrepancies.

Usage: python scripts/transcribe_training_narration.py narration.mp3 transcript.json
"""

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="small.en")
    args = parser.parse_args()
    audio = args.audio.resolve(strict=True)
    output = args.output.resolve()
    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type="int8",
        download_root=str(output.parent / "models"),
    )
    segments, _ = model.transcribe(
        str(audio), language="en", word_timestamps=True, beam_size=5, vad_filter=False
    )
    result = [
        {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": [
                {
                    "start": word.start,
                    "end": word.end,
                    "word": word.word,
                    "probability": word.probability,
                }
                for word in segment.words
            ],
        }
        for segment in segments
    ]
    output.write_text(json.dumps(result, indent=2))
    print(f"Saved {len(result)} segments to {output}")


if __name__ == "__main__":
    main()
