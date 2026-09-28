# Runway production log

2026-09-25: the owner approved the Module 1 written package and pilot production with “looks good lets do it.” Gate 2 is approved for this revision. Gate 3 (pilot review), Gate 4 (full Module 1) and Gate 5 (full Core series) remain pending. Official publication remains blocked until owner review of finished media.

| Module / scene | Script / prompt reference | Model / tool | Generation ID | Date | Duration | Credits used | Status | Approved / rejected | Rejection reason | Final durable location |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M01 pilot planning | VIDEO_PRODUCTION.md / PILOT_NARRATION.txt | Planning record; no generation | — | 2026-09-25 | Initial target 90s; edit adjusted to 72s | 0 | Superseded by final edit below | Written package approved | — | docs/training/VIDEO_PRODUCTION.md |
| M01 pilot narration | PILOT_NARRATION.txt, exact approved text | generate_speech; eleven_multilingual_v2; Benjamin; speed 1; en | c299527b-79c6-4155-8a43-dae033b4eeac | 2026-09-25 | 68.499s provider reported | 22 (balance 5677 → 5655) | Generated; exact script transcription verified | Owner review pending | — | .local-artifacts/training-pilot-v1/narration-original.mp3 |
| M01 pilot shot A | VIDEO_PRODUCTION.md base prompt + A, canonical public reference | kling-o3-pro; 1080p; 16:9; 10s; native audio off | 1c2e494f-cb4a-46d7-9809-31991f03d522 | 2026-09-25 | 10.041s source; 10s used | 170 (balance 5655 → 5485) | Generated; technical visual review passed | Owner review pending | — | .local-artifacts/training-pilot-v1/shot-a.mp4 |
| M01 pilot shot B | VIDEO_PRODUCTION.md base prompt + B, same reference/settings as A | kling-o3-pro; 1080p; 16:9; 10s; native audio off | 9f0f6f83-d5e4-428a-ae45-fd428be6e015 | 2026-09-25 | 10.041s source; 10s used | 170 (balance 5485 → 5315) | Generated; technical visual review passed | Owner review pending | — | .local-artifacts/training-pilot-v1/shot-b.mp4 |
| M01 pilot shot C | VIDEO_PRODUCTION.md base prompt + C, same reference/settings as A | kling-o3-pro; 1080p; 16:9; 10s; native audio off | 33cdada2-7514-4585-9b76-7adc09bcf56a | 2026-09-25 | 10.041s source; 10s used | 170 (balance 5315 → 5145) | Generated; technical visual review passed | Owner review pending | — | .local-artifacts/training-pilot-v1/shot-c.mp4 |
| M01 pilot delivery v1 | Executed edit in VIDEO_PRODUCTION.md; scripts/render_training_pilot.py | Local assembly; no provider generation | Local export | 2026-09-25 | 72.000s | 0 additional; 532 total | Export and technical QA complete | Gate 3 owner review pending | — | .local-artifacts/training-pilot-v1/guru-academy-pilot-v1.mp4 |

Technical review: narration's independently transcribed word sequence matches the exact approved script. Original speech is 68.499 seconds; the edit is 72 seconds, within the approved 60–90 second gate. No narration time-stretch or truncation. Shot A's half-second review frames show preserved identity, sealed rigid helmet and visible hands throughout its welcome gesture. Runway returned 1764×1176 (3:2), despite a 16:9 request; the final composition contains the entire image in 1920×1080, without stretching or forehead cropping. Technical review does not replace owner acceptance.

Append one row per generated asset, including rejected attempts. Never replace an old generation row with its retry. Record source identity references, exact tool settings, actual charged credits when available, final measured runtime, approved owner/date and where the source/master/delivery files were archived. Do not paste credentials or temporary signed URLs into Git. Unknown credits remain “not reported,” not zero. Gate approvals should be recorded here with the owner's decision and the specific revision approved.

## Pilot production authorization

One narration take plus three 10-second character shots. Initial estimate/cap: 532 credits (22 speech + 3 × 170 video), using [Runway published workspace pricing](https://academy.runwayml.com/models-pricing), checked 2026-09-25. No automatic paid retries. Provider-reported actual charges take precedence over estimates. All final pilot media stays in the ignored `.local-artifacts/training-pilot-v1/` directory for review; it is not an official lesson or production-hosted asset.

- Approved source MODULE_01_PACKAGE.md: SHA-256 `ce3cadaa33a137e333374aeceb49cc5a2856fe7bb56b4965d1663ee7b7297190`
- Approved source PILOT_NARRATION.txt: SHA-256 `ecb5e971615937bcfa2c59d8cde83509ed2d4b36b9162afe827928b92c2681c8`

## Delivery and QA — 2026-09-25

- Final MP4: 13,537,424 bytes; SHA-256 `cebd14d8f4fd1a5c3ec1b3d2579d0782a719c9b58dbd90bdfa46caaae61e8ff5`.
- 1920×1080, 30 fps, 2,160 frames, H.264 video / AAC audio; both streams run 72.000 seconds. Fast-start MP4. Entire video/audio decode completed without errors.
- Audio measured on the final encoded delivery: **-16.47 LUFS integrated, -1.44 dBTP**. The complete spoken excerpt is present. No music, generated scene audio, or narrator timing changes.
- 24 caption cues, exact approved words/punctuation, 00:00.000–01:07.800. Cues do not overlap; the shortest lasts 1.28 seconds. Burned-in captions, a separate `guru-academy-pilot-v1.vtt`, and an English MP4 text track are included.
- All three character clips inspected in half-second review frames, plus composited gesture frames. No visible mouth or lip articulation; identity, torso, hands and helmet framing retained. Violet emission uses the narration envelope on a constrained, tracked visor mask. A/B response was additionally checked across all 300 frames of each shot.
- Source CRM capture uses an isolated synthetic database and fictional Northstar Services record. No outreach or booking was submitted. Captured form details are followed by an authored handoff summary; an overly enlarged note screenshot was removed from the final cut for readability.
- Inspected the instructional layouts, caption placement, section changes, shot overlays and end hold. Browser automation rejected local-file playback under its URL policy; no bypass was attempted. The finished MP4 was submitted to Codex's native workspace-file preview. **Continuous human viewing/listening, voice acceptance, headphone/laptop listening and employee/CDN playback remain pending**, not passed by these offline checks.
- The final export, original narration, three source videos, exact request/result records, frame review images, caption alignment and measurements remain locally in the ignored production folder. This is a local review archive, not durable hosted employee media. Temporary provider URLs are not committed.
- Provider-reported balance: 5,677 → 5,145; **532 credits**, four generation calls, no rejected takes, no paid retries. Gate 3 acceptance is still pending; no full lesson or series has been generated or published.

## Website voice correction — 2026-09-27

Owner feedback: “this is EXACTLY what I wanted however.... his voice is different then Guru thats on the website already can we fix that?” This accepts the visual direction and authorizes correcting the pilot voice. It does not authorize full-lesson or series production. The original rows above remain the historical production/review record; Benjamin narration is now rejected for voice mismatch, and the three visual shots are accepted for reuse.

Read the existing Guru character from the developer API: avatar `b6494a17-6106-4592-9e52-e6685a76e830`, voice type `runway-live-preset`, preset `vincent` (Vincent / Knowledgeable). Generated a scripted recording from that exact character using `POST /v1/avatar_videos`, `gwm1_avatars`, and the approved text with no voice override. No live avatar fields, personality, site configuration or production secrets were changed. Only this recording's audio is used; its video is retained as a source archive, not as accepted helmet footage.

| Module / scene | Script / prompt reference | Model / tool | Generation ID | Date | Duration | Credits used | Status | Approved / rejected | Rejection reason | Final durable location |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M01 pilot narration v2 | PILOT_NARRATION.txt; existing Guru character and configured voice | avatar_videos; gwm1_avatars; live Vincent | a26eb348-0871-4337-bd5c-bb7095669254 | 2026-09-27 | 70.827s extracted audio | 2 developer API credits; task-reported cost; balance 9308 → 9306 | Generated; audio extracted and aligned | Requested voice identity matched; owner listening pending | — | .local-artifacts/training-pilot-v2/voice-source.mp4 and narration-original.wav |
| M01 pilot delivery v2 | Same visual sources and script; edit.json retiming | Local assembly; no further provider generation | Local export | 2026-09-27 | 74.000s | 0 additional | Export and technical QA complete | Visual direction accepted; corrected voice review pending | — | .local-artifacts/training-pilot-v2/guru-academy-pilot-v2.mp4 |

- Final MP4: **13,724,438 bytes**, SHA-256 `ad44cd72f367d671d46c509052868f2046ebcae1f0af318cc61b2ec9af0103d5`.
- 1920×1080, 30 fps, 2,220 frames, H.264/AAC with English MP4 text track and WebVTT. Video and audio both 74.000 seconds. Full decode passed.
- Final encoded audio: **-16.67 LUFS integrated, -1.35 dBTP**. Original narration is not sped up, truncated or mixed with source scene sound. The final hold follows the complete speech.
- Independent local ASR matched all script content after one explicitly recorded equivalent contraction: “Here's” → “Here is”. Raw recognition output is preserved. No substantive words were omitted, added or reordered. Captions retain approved script punctuation. 24 cues; no overlaps; last cue ends 70.720s, shortest cue 1.140s.
- Character footage and CRM source hashes match v1 exactly. Shots remain ten seconds each at natural speed. Revised timeline: A 0–10; habits 10–18.5; B 18.5–28.5; working-day diagram 28.5–40.3; CRM 40.3–54.3; C 54.3–64.3; workflow/closing hold 64.3–74. Violet emission and captions follow the new audio; no lip animation is added.
- Inspected revised welcome, principle, CRM, example and closing frames. Owner hearing of the corrected delivery remains pending; technical checks do not claim a human listening test. Submitted for native workspace preview; no browser-policy bypass attempted.
- Exact request/result records, raw returned recording, extracted narration, ASR, edit anchors, captions, final output and QA metadata are archived in the ignored v2 folder. V1 remains available. No media published, no full-module generation and no paid retry batch. Two developer API credits are separate from the original 532 connected-workspace credits.

## Full Module 1 — approved pilot, production on 2026-09-27

The owner accepted corrected pilot v2 with “perfect lets do the rest.” Gate 3 is approved for that exact 74-second revision. The full first lesson is the next review artifact under Gate 4; this does not publish the lesson or authorize a batch of remaining Core modules. The explicit same-day pricing amendment is included: custom to the recommended build, only a qualified human AI Specialist, only during a Growth Assessment.

All narration uses the existing live Vincent avatar configuration with no voice override. Chapter 1 reuses the first 54 seconds of accepted v2 narration. Thirteen chapter recordings and two targeted restorations were generated; each reports 2 developer API credits. Total: **30 developer API credits**, balance **9,306 → 9,276**. Body sources A–C are reused; six new body clips cost **1,020 workspace credits**, balance **5,145 → 4,125**. No top-up is required for this lesson. The balances are separate.

| Asset | Generation ID | Source duration | Credits | Review / use |
| --- | --- | --- | --- | --- |
| Narration 02 | `9c85b9ec-455b-42ec-907c-177e1d5b601a` | 60.203s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 03 | `76adf92e-5952-4a40-8e81-37a0cc1cb485` | 56.619s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 04 | `6bd072a3-4aec-4bc2-8312-1c748108a77d` | 59.861s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 05 | `09411747-3bd2-4f6f-a536-272637a8d284` | 68.181s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 06 | `b594367c-a250-40a3-817f-80a61651179e` | 57.472s | 2 developer API | Original omitted a passage; retained and repaired below before assembly |
| Narration 07 | `ad12a9dd-4baa-4e3f-81a9-2f5c97349fc5` | 57.152s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 08 | `cd0d29f8-0fad-4695-8efd-4cb573a7b537` | 78.549s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 09 | `b1407db6-7ba2-4bfc-b192-431868f3bcd1` | 54.187s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 10 | `87c69ca1-d5c3-4de4-89f7-403451ec18d7` | 65.344s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 11 | `b3c45f2d-bab7-4b99-9e88-6d1f932939f3` | 81.579s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 12 | `8e6eb0be-8e4f-4de8-8626-f1ff7c7fb996` | 57.579s | 2 developer API | Original omitted a passage; retained and repaired below before assembly |
| Narration 13 | `c9f93acd-15b5-45a1-8878-368487f427b0` | 63.829s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 14 | `65980c05-0504-4c6c-923a-815af15db99f` | 82.347s | 2 developer API | Approved words verified after documented ASR normalization |
| Narration 06 missing passage | `5773eee2-0178-4855-87f2-def5a7a73f87` | 5.013s | 2 developer API | Exact requested passage verified, inserted between phrases; original take preserved |
| Narration 12 missing passage | `c0872234-a2da-4a0e-92e6-6670082e3f65` | 7.296s | 2 developer API | Exact requested passage verified, inserted between phrases; original take preserved |
| Body D | `31f87458-0e54-4d87-9fa9-6909e8c35e8c` | 10.041s; 10s used | 170 workspace | Identity, sealed helmet, torso/hands verified in 20 half-second review frames |
| Body E | `f4238e9e-e124-4cb6-9d8f-8f35290d8212` | 10.041s; 10s used | 170 workspace | Identity, sealed helmet, torso/hands verified in 20 half-second review frames |
| Body F | `28203360-3968-424d-8d8f-66302b1bcdc6` | 10.041s; 10s used | 170 workspace | Identity, sealed helmet, torso/hands verified in 20 half-second review frames |
| Body G | `730dc140-1a22-4d78-9cdb-967616f94827` | 10.041s; 10s used | 170 workspace | Identity, sealed helmet, torso/hands verified in 20 half-second review frames |
| Body H | `9868c4b1-4a5a-47e7-b46e-3830eed993f3` | 10.041s; 10s used | 170 workspace | Identity, sealed helmet, torso/hands verified in 20 half-second review frames |
| Body I | `7d6a228e-2509-406c-9718-66713ba8928a` | 10.041s; 10s used | 170 workspace | Identity, sealed helmet, torso/hands verified in 20 half-second review frames |

Source records, original takes, exact prompts, repairs, raw ASR, explicit transcription spelling review, frame reviews and assembly are archived under `.local-artifacts/module-01-v1/`. Sources use `kling-o3-pro`, 1080p, requested 16:9, 10 seconds, no source audio, and the same canonical Guru reference as the approved pilot. Returned 3:2 images are contained without stretching or cropping. Nine unique ten-second clips provide fourteen chapter introductions; teaching boards and pauses occupy the remainder. No long synthetic talking loop.

The verified edit has **2,111 spoken words, 14 chapters, 62 teaching boards, 280 caption cues and 52 seconds of practice pauses**. Planned 15:00 pacing resolves to **973.533 seconds (16:14 rounded)** at natural speed. Chapter 11 contains the new pricing rule; no price figures are spoken. The CRM captures use an isolated fictional record; no real prospect data, invitation or outreach. Final export QA is recorded separately after encoding.

## Full Module 1 delivery and QA — 2026-09-27

- Review export: `.local-artifacts/module-01-v1/guru-academy-module-01-v1.mp4`, **90,133,738 bytes**. SHA-256 `207c054bd7f64b110919346327235e75d6ede0018cc58b5d453c4502c3561894`.
- Measured duration **973.533 seconds (16:14 rounded)**, **29,206 frames**, 1920×1080, 30 fps, H.264/AAC 48 kHz. Complete audio/video decode passed with no errors. Video and audio duration agree; MP4 fast-start verified.
- Final encoded audio: **-16.65 LUFS integrated, -1.31 dBTP**. No speech speed change, truncation, music or generated scene audio. Three pauses total 52 seconds. Both restored passages use the same configured Vincent voice; original takes remain archived. Splices are within quiet gaps with no clipped word timestamps.
- **280 synchronized cues** in burned-in captions, English MP4 text and separate `captions.vtt`. Exact 2,111-word script is represented after explicit acronym/number/contraction and documented ASR spelling normalization. Short isolated sentence endings were merged for readability. No cue overlaps or cues beyond duration; shortest cue 0.700s (three short words), last cue ends 969.693s. Chaptered `transcript.txt` is included.
- Inspected all 62 teaching layouts, representative composites across all 14 chapters, all three practice cards, detailed pricing/qualification/CRM frames and all new body sources. Preserved sealed helmet, visible torso/hands and natural ten-second motion. Captions stay below the instructional content. Frame reuse optimization was verified against 615 pixel-identical rendering pairs; animation frames remain intact.
- Existing Academy tests: **35 passed**. Policy revision preserves prior content, quiz attempts and employee progress. Current local Module 1 version 2 remains in owner review; no official training published.
- Approved current content source SHA-256: `5af521a1b85dee20f4a3988c84e587189a10798de4e5689336e95ab2fea8fa16`. Original draft scene timings are planning values; use the measured `edit.json` chapter boundaries and 974-second rounded duration when attaching this accepted film to a published module version.
- Remaining acceptance: owner continuous viewing/listening and full-lesson approval, private employee media hosting, production range/caption/playback checks and actual live Academy provider integration. These checks do not claim a human listening test. **Gate 4 is ready for owner review.** Remaining Core videos have not been generated. No commit, deployment or publication performed.

### Measured chapter starts

- 00:00 — Your job begins with their business
- 00:54 — What AI Business Gurus does
- 01:55 — The SDR mission and boundaries
- 02:52 — The complete customer journey
- 03:53 — Problem first: hear the difference
- 05:02 — Your turn: follow the answer
- 06:20 — Natural openings and helpful gatekeepers
- 07:18 — What makes an assessment qualified
- 08:37 — Earn the Complimentary Growth Assessment
- 09:32 — The handoff is part of the win
- 10:38 — Ethics, accuracy and price boundaries
- 12:00 — Objections and knowing when to leave
- 13:06 — Practice, feedback and the second attempt
- 14:47 — Your standard and next action

## Core-series production authorization — 2026-09-27

The owner accepted the exact full Module 1 export with SHA-256 `207c054bd7f64b110919346327235e75d6ede0018cc58b5d453c4502c3561894`: “this video is PERFECT! keep going. I need this whole thing done by tomorrow.” Gate 4 is approved; production of the remaining Core SDR series (Gate 5) is authorized. The owner then explicitly prioritized the complete 16-lesson Core SDR Academy. The approved full lesson sets the voice, visual and teaching standard. Final remaining-series acceptance and employee publication remain distinct from generation.

Production will reuse the nine accepted Guru motion shots as an instructor library and generate new exact Vincent narration for each lesson. Estimated narration: 15 lessons × 12 chapters × 2 credits = 360 developer API credits, plus a capped 90-credit correction reserve; 450 developer API-credit budget. No new paid motion footage is needed for this stage. Existing workspace balance is separate. Credit/cost changes or storage blockers will be reported promptly.

## Complete Core delivery — 2026-09-28

All **16 films** are complete: **14512.300 seconds (4 hours 2 minutes)**, **1,281,449,973 video bytes**, **194 chapters**, **4,038 caption cues** and **33,170 spoken words**. Each module includes its field guide, quiz/answer explanations and fictional practice scenario; the series contains 132 quiz questions and 16 scenarios. All 626 teaching-board layouts passed overflow measurement, with representative visual inspection across every lesson.

The accepted Module 1 film remains byte-for-byte unchanged. All exports are 1920×1080 H.264 at 30 fps with AAC 48 kHz audio, fast-start MP4, English embedded and burned-in captions, and separate WebVTT. Full audio/video decoding, chapter order, caption timing, content/source hashes and loudness checks passed for each film.

Encoded loudness spans -16.88 to -16.32 LUFS; highest true peak is -1.29 dBTP. Recognition checks compare against the canonical scripts with explicit spelling and word-boundary review. Real omissions/mispronunciations were corrected with the same avatar; original and rejected takes remain preserved. These automated and focused checks do not claim continuous human listening.

Runway generation for Modules 2–16 cost **438 developer API credits**: 360 for 180 base narration tasks and 78 for original/correction takes. This stays within the 450-credit stage budget. No new motion footage was purchased; the nine accepted Guru shots were reused. Final developer balance was **8,838 credits**. Historical pilot/Module 1 and workspace charges remain separate above.

| Module | Runtime | Video bytes | SHA-256 prefix |
| --- | --- | ---: | --- |
| 01 | 16:14 | 90,133,738 | `207c054bd7f64b11` |
| 02 | 16:00 | 81,689,432 | `a674702c49a6368f` |
| 03 | 17:27 | 84,787,021 | `00c6c07936ba6b4e` |
| 04 | 15:41 | 79,311,870 | `c0ec1a183af960b3` |
| 05 | 14:42 | 78,881,834 | `01f4f9682b4ec076` |
| 06 | 14:42 | 78,405,057 | `e5fa03fe736bbedf` |
| 07 | 14:27 | 79,381,435 | `3b0de7af8d7a8431` |
| 08 | 14:43 | 78,891,394 | `771ed125bb6b8902` |
| 09 | 15:00 | 79,535,369 | `b9aebba65a194803` |
| 10 | 14:42 | 79,429,529 | `2550a7fb9f5c6cfd` |
| 11 | 14:16 | 77,282,013 | `cc3cb2b4702542c8` |
| 12 | 15:05 | 79,335,521 | `e7eef89bdf05ea75` |
| 13 | 14:32 | 76,755,088 | `94d322fc72a65ead` |
| 14 | 14:05 | 77,400,086 | `e3de56b2726f8af4` |
| 15 | 14:46 | 78,925,915 | `c56467f53371a4e3` |
| 16 | 15:30 | 81,304,671 | `9f4309fe3f25321b` |

Full hashes and per-film technical reports are included in the delivery folder. The Module 1 QA report is the preserved historical report from before owner acceptance; its later accepted status is recorded in the manifest and this log.

Delivery folder: `deliverables/Guru-Core-SDR-Academy`. Use its `START-HERE.md`, `manifest.json`, `SHA256SUMS.txt` and `Render-setup.md`. Upload the entire folder to a private Render persistent disk; deploy matching application code, then verify/import using the documented command. The importer does not publish lessons or award employee credit.

Application validation includes the complete Django regression suite, 45 audio/interface JavaScript tests, private range playback and seek beyond five minutes, video-reload position and speed handling, and a 390-pixel phone layout with no horizontal overflow. Global gzip compression is explicitly bypassed for private media so byte-range responses retain their original bytes and lengths. Guru teaching context now prioritizes the current lesson field guide over older history.

Remaining release steps are owner review of the remaining films and the owner’s Render storage/deployment/publication workflow. Actual live Academy coaching with a human participant and production media playback still require acceptance on the deployed configuration. The local optional text-AI credential remains absent, so written practice explicitly identifies guided rehearsal unless the deployed credential is configured. No real prospect outreach, commit, deployment or employee certification was performed.
