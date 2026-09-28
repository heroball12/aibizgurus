# Guru production plan

**CURRENT STATUS — the owner accepted the corrected website-Vincent pilot and the complete Module 1 film on 2026-09-27, then authorized all remaining Core SDR films. The historical pilot plan below is preserved for provenance; use the current Core delivery section and production log for active scope.**

## Approval sequence

Gate 1: architecture/curriculum implementation for review. Gate 2: [complete Module 1 written package](MODULE_01_PACKAGE.md). Gate 3: a 60–90 second pilot. Gate 4: one complete approximately 15-minute Module 1 video. Gate 5: full Core SDR series production. These gates come from owner-policy sections 46 and 74. Written approval is not voice, pilot, full-video or publication approval.

## Exact pilot specification

Target **90 seconds**, 1920×1080, 16:9, 30 fps, H.264/AAC delivery. Three distinct 10-second Runway Guru body-motion shots; the other 60 seconds use authored animated diagrams, typography and one synthetic CRM demonstration. One continuous narration master, not independently improvised dialogue in each shot. No stretched still or idle loop is described as generated character footage.

Reference identity: `static/img/guru-helmet.jpg`. Graphite sealed helmet, gold mechanical details, narrow violet visor, no visible mouth. Keep torso/hands visible with generous headroom. Use controlled presenter gestures, not rooftop parkour in an instructional shot. The violet visor's brightness follows narration amplitude; its geometry stays fixed. Track/mask the light in the edit if the generation cannot reliably preserve it. Do not claim this has already been demonstrated.

**Original voice proposal (superseded 2026-09-27):** Benjamin, a calm deep male narration voice; steady speech engine, speed 1.0, English. This was a production audition, not a verified match to the existing live Guru voice. The owner requested the website voice after reviewing it. Use the voice identity below for revised narration. Use sentence punctuation for delivery; no spoken stage directions. No backing music in the pilot, so speech intelligibility is easy to assess.

### Website voice identity — verified 2026-09-27

The existing custom character **Guru — AI Business Gurus** (`b6494a17-6106-4592-9e52-e6685a76e830`) is configured with `runway-live-preset`, preset ID **`vincent`**, name **Vincent**, description **Knowledgeable**. Read the actual character before future production and compare this identity; do not change the website character to fit a training take.

Use `POST /v1/avatar_videos`, model `gwm1_avatars`, `avatar: {type: "custom", avatarId: <existing Guru ID>}`, and `speech: {type: "text", text: <approved script>}`. Omit the optional speech voice override so the recording uses the character's configured voice. This behavior is documented in the [official Runway SDK schema](https://github.com/runwayml/sdk-python/blob/main/src/runwayml/types/avatar_video_create_params.py). The connected speech tool's capitalized `Vincent` belongs to a separate voice library and is not an established match. Do not substitute it based on the name alone.

Only the returned audio is used in the revised pilot. Retain the owner's approved sealed-helmet body footage, retime the supporting graphics, align captions again and regenerate the violet light from the new narration. No new character footage, avatar mutation, paid retry batch or full lesson is needed for this correction. Archive v1 unchanged and place revised assets in `.local-artifacts/training-pilot-v2/`.

**Corrected delivery v2:** 74 seconds, completed 2026-09-27. Original Vincent narration is 70.827 seconds, with no speed adjustment or truncation. Shots A/B/C remain ten seconds each at 00:00, 00:18.5 and 00:54.3. The same graphics are retimed around the new delivery. Runway charged **2 developer API credits**, reported on task `a26eb348-0871-4337-bd5c-bb7095669254`; one request, no retries. See the production log for validation and the separate original workspace costs. Reproduce the edit with `scripts/render_training_pilot.py --workdir .local-artifacts/training-pilot-v2 --edit .local-artifacts/training-pilot-v2/edit.json` using the documented build dependencies.

| Timeline | Picture / motion | Narration / purpose |
| --- | --- | --- |
| 00:00–00:10 | Shot A: Guru, medium-wide, short open-palm welcome; identity and violet speech light clearly visible | Introduction from the exact excerpt |
| 00:10–00:30 | Animate LISTEN → ASK → TELL THE TRUTH → HAND OFF. Reveal one item at a time; no feature wall | Explain what a new SDR actually needs to do |
| 00:30–00:40 | Shot B: same identity/framing, right-hand gesture toward the emerging problem card | Problem first, technology second |
| 00:40–01:00 | Four-stage customer journey. Highlight unanswered follow-up, repetitive work and disconnected handoffs | Show the business problems in the narration |
| 01:00–01:15 | Synthetic CRM visual: FACT / HYPOTHESIS / NEXT STEP cards, then a quote-follow-up workflow. No actual outreach/calendar submission | Mission and handoff; introduce the example |
| 01:15–01:25 | Shot C: Guru lowers an open hand and gives one measured nod; no camera push into the forehead | Match the quote problem to a possible follow-up process |
| 01:25–01:30 | Finish on the workflow with “Follow the problem. Verify the fit.” and an accessible end hold | Finish the final sentence, leave a short reading beat |

This is the edit decision plan. Fit the approved voice to the 90-second timeline by trimming diagram holds and editing between sentence boundaries, not by truncating speech or stretching Guru footage. If natural delivery cannot fit, revise the cut within the 60–90 second gate or bring the specific script change back for review.

### Executed pilot edit — 2026-09-25

The approved narration runs 68.499 seconds naturally. Delivery is **72 seconds**, inside Gate 3's 60–90 second range. Speech is neither time-stretched nor truncated. The initial 90-second timing above is preserved as the planning record.

| Time | Delivered picture |
| --- | --- |
| 00:00–00:10 | Guru welcome, shot A |
| 00:10–00:16.6 | Four conversation habits, progressive reveals |
| 00:16.6–00:26.6 | Guru principle, shot B |
| 00:26.6–00:38.7 | Customer / repetitive-work / handoff diagram |
| 00:38.7–00:51.5 | Captured synthetic CRM views; fact, hypothesis, next step |
| 00:51.5–01:01.5 | Guru quote example, shot C |
| 01:01.5–01:12 | Quote / follow-up / human-team workflow and reading hold |

The three sources were returned at 1764×1176 (3:2). They are contained in 1920×1080 without distortion or head cropping. There are 30 seconds of distinct generated character motion and 42 seconds of authored instructional graphics/CRM material. Original audio remains intact. A masked violet emission follows the narration's RMS envelope on the existing visor pixels; it does not animate a mouth.

Offline build tools: `scripts/transcribe_training_narration.py` (faster-whisper; small.en; CPU int8) and `scripts/render_training_pilot.py` (Pillow, numpy, imageio-ffmpeg). These are production-workstation dependencies, not web-app requirements. Generated media, models and private result manifests stay under the ignored `.local-artifacts/training-pilot-v1/` directory. The renderer compares the independently recognized words with the approved script, restores exact script punctuation, and emits burned-in captions plus WebVTT/MP4 text tracks.

## Exact spoken excerpt

Source: Module 1 scene 1, followed by the quote-follow-up example from scene 2. **172 words; 1074 characters.** Also saved as [PILOT_NARRATION.txt](PILOT_NARRATION.txt).

Welcome to AI Business Gurus. I'm Guru, your AI sales trainer.
You do not need to become a software engineer before your first supervised call. You do need to listen, ask useful questions, tell the truth, and leave the next person with useful information.
Here is the principle that runs through this Academy: problem first, technology second. A business owner rarely wakes up hoping to hear a list of artificial intelligence features. They wake up thinking about customers who did not call back, employees buried in repetitive work, and opportunities that disappeared between one system and another.
Your job starts there. By the end of this lesson, you should be able to explain our mission, recognize a qualified assessment, and write a handoff that helps our human specialist move the conversation forward.

Imagine a company that answers every incoming call but loses track of quotations after sending them. Another phone-answering tool may not solve its problem. A consistent follow-up process, connected to the right records and human team, might be worth exploring.

## Original generation instructions (v1 production record)

The following records the completed original production. For narration revisions, use the verified website voice identity above; do not repeat the Benjamin audition or regenerate accepted shots.

1. Recheck the connected workspace and available tools with `runway_whoami`. The connection authenticated on 2026-09-25; body-motion video and speech tools are available. No new account is required for the connected generation tools.
2. Resolve the canonical Guru image from the existing Runway library. Inspect that it matches the repository reference; do not substitute a similar robot. If no matching hosted asset exists, use the supported upload flow for the approved reference.
3. Generate one narration master with `runway_generate_speech`, proposed voice Benjamin, `eleven_multilingual_v2`, speed 1.0, language en, exact text above. Tool-estimated narration cost is **22 credits** at its current 1/50-character rule. Actual charge belongs in the log; revisions cost extra. Listen before requesting body shots. Do not synthesize all 16 scripts.
4. Proposed body-motion tool: `runway_generate_video`, `kling-o3-pro`, ratio 16:9, duration 10 for each of A/B/C, resolution 1080p, native audio off, canonical identity reference. It is available in the verified workspace. Recheck exact cost before submission; do not invent a fixed video cost or treat API dollar pricing as workspace credits.
5. Apply the base prompt below plus the shot-specific action. Generate one candidate per shot initially. Review it before retrying. Stop on identity/visor failure; avoid speculative generation batches.
6. Assemble in an editor with accurate authored graphics, recorded synthetic CRM material, audio-responsive violet light and aligned WebVTT captions. Normalize speech consistently, keep true peaks below clipping, inspect headphones and laptop playback. Log the actual loudness measurement; -16 LUFS integrated / -1 dBTP is a **PROPOSED** web delivery target.
7. Preview the actual finished pilot with audio for the owner. Save source references, task IDs, settings, durations and credits in the production log. Do not publish it as an official module.

**Base shot prompt**

“Use the supplied Guru identity exactly. A premium graphite-and-gold AI robot instructor sits at a simple glossy desk in a quiet futuristic AIBG studio, purple architectural lighting, restrained gold accents, uncluttered dark background. Medium-wide composition showing the entire helmet, torso, both hands and desk surface with comfortable headroom. Fixed camera, natural restrained presenter posture. The entire helmet is rigid opaque metal. The narrow horizontal violet visor keeps its exact shape. There is no mouth, no lips, no teeth, no moving jaw, no facial articulation, no visor stretching or talking-eye deformation. Body and hand motion only. Preserve the reference proportions and materials throughout. No generated lettering, no subtitles, no audio.”

A: “One short open-palm welcome at waist height; settle naturally.”
B: “One slow right-hand gesture toward empty space on the right for a diagram; return to neutral.”
C: “A small open-hand emphasis, then lower the hand and give one measured nod. Keep the helmet rigid.”

## Acceptance and credit control

Approve voice/tone/pacing, face rigidity throughout the clip, body/hand quality, framing, exact brand colors, readable graphics, synchronized violet light, actual sound, caption accuracy and transitions. Inspect representative frames at start/middle/end and each gesture, plus continuous playback. A visor that opens like a mouth fails. So do lips, feature drift, forehead crops, invented policy, illegible CRM steps, missing audio or static padding.

A total video credit estimate and one-pilot cap must be recorded before generation. No full-course budget is presumed approved. The approved pilot cap is **532 credits** (22 narration + three 170-credit shots), with no automatic paid retries. Provider-reported charges and production status are maintained in [RUNWAY_PRODUCTION_LOG.md](RUNWAY_PRODUCTION_LOG.md). Each further media stage waits for its gate.

## Long-form production and storage

The connected generator creates short clips, not one uninterrupted 15-minute teaching performance. The [Runway script-to-video guide](https://help.runwayml.com/hc/en-us/articles/51285026291219-Character-Script-to-Video) discusses assembling longer material. Live [Characters sessions](https://docs.dev.runwayml.com/characters/concepts/) are a different product from prerecorded lessons. Tool availability and pricing must be checked at production time; see [Runway pricing](https://docs.dev.runwayml.com/guides/pricing/).

After an approved pilot, assemble Module 1 from its full narration, varied approved Guru shots, diagrams and real synthetic CRM recordings. Align [draft captions](MODULE_01_CAPTIONS_DRAFT.vtt) to the actual audio. Keep source renders and masters out of Git. Use versioned durable private object keys such as `training/core-sdr/01/v1/lesson.mp4` and `captions.vtt`; store only keys in LessonAsset. A temporary generation URL is not the permanent employee video URL.

The player expects MP4 range requests and captions served with correct content types. Configure `TRAINING_S3_BUCKET`, optional `TRAINING_S3_REGION` and HTTPS `TRAINING_S3_ENDPOINT`; grant the app read-only object access through the standard AWS credential chain. Allow GET/HEAD and Range from the exact site origin in storage CORS; expose Content-Range/Accept-Ranges/Content-Length. Keep the bucket private. Upload/review with a separate producer identity. See [Boto3 presigned URL documentation](https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html).

Production acceptance must exercise login, playback past five minutes, seek after URL expiry and the player's Reload video control, captions, speed, resume, phone playback and unauthorized access. Signed links last five minutes and authorize the media bearer until expiry; they are not DRM. Production storage acceptance remains pending. The private-disk alternative below has been exercised locally, including range playback and seeking beyond five minutes.


## Core delivery folder and Render disk option — 2026-09-27

The owner accepted the corrected full Module 1 film and authorized all remaining Core lessons, prioritizing the 16-lesson Core Academy for September 28 at 08:30 America/Los_Angeles. They requested a folder of completed videos to upload to Render. See [Render delivery](RENDER_DELIVERY.md) for the private persistent-disk workflow. This is an alternative to the S3 configuration above; no bucket or paid Render disk was provisioned by this work.

`scripts/package_training_bundle.py` refuses to package an incomplete series or a film whose bytes, source hash, duration or QA report disagree. The final folder contains the 16 films, WebVTT captions, posters, chaptered transcripts, field guides, scenario quizzes with manager answer keys, technical reports and an import manifest. The command `import_training_bundle --check` verifies the complete folder without writing records; importing attaches review assets and actual timings without publishing or awarding credit.

Core narration retains the existing live Vincent avatar configuration. The accepted nine-shot Guru library is reused at natural speed with rigid helmet and audio-responsive violet emission. Teaching boards and actual CRM captures carry the lesson content. Module 6 changes the pace and dynamics only within three short comparison openers to demonstrate mechanical, rushed and hesitant delivery; the calm example and surrounding narration use their original delivery. No voice identity or pitch is substituted. Original takes and the local edit record are preserved.
