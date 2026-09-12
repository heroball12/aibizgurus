# AI arrival landing film

## Production status

The landing now includes the completed Runway film with sound: 15.1 seconds, 1916 × 1080, 24 fps, H.264 video and AAC stereo audio. The reviewed sequence includes the rooftop sprint, vault and aerial flip, gap jump, descent past the **your company** sign, and the robot seated and typing at a desk. The film is bundled with the landing update. Production deployment through the existing Git → Render flow remains a separate step.

Runway task: `598214ab-a29c-4841-a495-3e875c67be91`. One generation used 259 credits. The first take satisfied the brief; no additional takes were submitted. The original master is preserved outside the Git repository in the task's `arrival-film` artifact directory. Temporary authenticated provider URLs are not embedded in the site.

Web delivery: `static/video/ai-arrival.mp4` (10,557,832 bytes). Scene descriptions: `static/video/ai-arrival.vtt`. The player starts muted, exposes sound, pause/play, replay and full-screen controls, and holds the final desk shot. It falls back to the original poster when media is unavailable. Mobile shows the complete 16:9 frame above the copy.

## Visual direction

- Original athletic humanoid robot: graphite/titanium armor, gold articulated joints, violet horizontal visor and chest core. Keep its body, faceplate, proportions, and materials consistent across every shot.
- Photorealistic cinematic city at night, rain-slick rooftops, violet atmospheric light, champagne-gold office interiors.
- Heroic, athletic rooftop parkour; no combat. The destination is a glass office building with the exact lowercase architectural sign **your company**.
- Finish with the robot seated at a desk, hands on the keyboard, working. The transition from extreme athletic movement into composed office work is the payoff.
- The poster is original built-in image generation, saved as `static/img/ai-arrival-poster.png`. It is a still image, not motion footage.

## Film sequence

The generated 15-second, 16:9 film follows these five beats:

1. **Rooftop sprint:** Low tracking camera beside the robot sprinting over a wet high-rise roof. Feet contact the surface, gold joints articulate, violet city reflections streak past. Mechanical footfalls and rushing wind.
2. **Parkour:** The same robot speed-vaults a rooftop obstacle, plants a hand, spins through an aerial side flip, and lands in stride. Continuous, readable athletic motion and consistent anatomy.
3. **The leap:** A wide cinematic view reveals the robot launching across a large rooftop gap. Camera arcs around it; it tucks and rotates, then extends toward the next ledge. Violet skyline, gold-lit glass tower ahead. One short moment of airborne slow motion.
4. **Your company:** The camera follows the robot dropping down the outside of the destination tower. Hold the exact sign “your company” visibly on the facade. An open architectural terrace leads into a warm, sophisticated office; the robot drops through this opening toward a workstation.
5. **Reporting for work:** Match the downward movement to a controlled landing beside the desk, then the robot drops smoothly into the office chair and starts typing at the computer. Close on articulate hands, then settle on the robot calmly working. Mechanical impact, chair movement, keyboard taps, and a quiet electronic resolution.

Keep any electronic underscore original. No dialogue is needed. Do not treat a generated clip as successful until all required actions and the building text have been visually checked. If signage is distorted, correct it before delivery. Do not replace the footage with a slideshow or animated still and describe that as parkour.

## Web delivery

- Export H.264, yuv420p, a conventional web-compatible MP4 with fast-start metadata and AAC audio.
- Start muted; a deliberate visitor action enables sound. Do not autoplay sound.
- Play through once and hold the desk scene. Provide pause/play, sound, and replay controls.
- Avoid automatic playback/download for reduced-motion and data-saving preferences. Pause offscreen or in a hidden tab.
- On mobile, preserve the robot and destination in the image crop; keep copy and controls below the visual.
- Keep the poster if playback fails. Keep navigation and demo links working.
- Include the final video and any caption file in the repo before Render collects static assets. Existing Render credentials and settings are unchanged.

## Rebuilding the delivery

Run `python scripts/prepare_arrival_video.py /path/to/reviewed-master.mp4` with the build-only `imageio-ffmpeg` package installed. This preserves the original, encodes the web MP4, normalizes sound for comfortable playback, and places fast-start metadata before media data. It replaces the delivery file only after encoding completes. Production needs no Runway credentials or rendering dependencies to play the bundled film.

Reference: [Runway image-to-video prompting guide](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide).

## Validation

The existing landing/industry regression test, Django system check and JavaScript syntax validation pass. Production static collection succeeds. Browser checks confirm playback reaches the end without media errors, starts muted, toggles sound, pauses/resumes, replays from the beginning, enters/exits full screen, pauses offscreen, and preserves a deliberate user pause. The 390-pixel mobile layout shows the full video without horizontal overflow. The video contains a non-silent AAC audio stream, verified from the exported media. The poster and navigation remain available independently of film playback.
