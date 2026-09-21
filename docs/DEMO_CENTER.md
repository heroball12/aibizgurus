# Category demo center

The demo page groups the 101 catalog industries into 13 video employees. Search matches both the category and every underlying industry. Each category has its own chat history, sample business, suggested questions and character. These demonstrations never create real appointments, orders, leads or service requests.

| Category | Employee | Appearance |
| --- | --- | --- |
| Food & dining | Sage | Chef coat, chef hat and bob hairstyle |
| Home services | Atlas | Work shirt and safety helmet |
| Healthcare & wellness | Nova | Clinical coat, purple scrubs and bun |
| Automotive | Axel | Mechanic coveralls |
| Beauty & personal care | Zuri | Salon apron and long violet-accented hair |
| Professional & property | Sterling | Suit and purple tie |
| Business & technology | Vega | Tailored jacket and sleek bob |
| Hospitality, retail & events | Aria | Hospitality uniform and long hair |
| Cannabis | MaryJain | Purple staff jacket, gold leaf pin and long violet-accented hair |
| Fitness & movement | Rio | Athletic jacket |
| Education & community | Mira | Cardigan, bob and violet hair clip |
| Pet services | Kai | Veterinary scrubs |
| Transport & logistics | Jett | Reflective vest and ponytail |

All portraits use sealed graphite helmets with a purple visor and gold details. The site adds a purple speech glow driven by the actual remote audio level. Runway does not expose a reliable lip-animation switch. The call UI keeps the original sealed-helmet artwork visible and subscribes only to live audio; the voice drives the purple light. This is explicitly labelled voice-reactive robot artwork, not continuous animated body video. The generated Guru gesture clip is a short visual transition played over the artwork when a website action occurs; live audio continues. Reduced-motion preferences suppress that clip.

MaryJain covers the existing Dispensary, Cannabis Delivery and CBD Store catalog entries, which previously belonged to Aria. Her fictional business is Violet Leaf. Both the Runway persona and text preview now provide cannabis education: chemistry, strain identity, medical research, effects, laboratory reports and industry terminology. The shared library has 26 topics and 22 linked sources, checked September 16, 2026. She distinguishes evidence for particular medicines from unverified claims about strains. She does not provide personal treatment or dosing, recommend products for purchase, take orders, arrange deliveries or collect private customer details. Guru includes her in the same personalized introduction flow as the other employees. See [CANNABIS_KNOWLEDGE.md](CANNABIS_KNOWLEDGE.md) for scope and maintenance.

## Conversations and handoffs

Text chat uses the existing platform OpenAI gateway. Without its configured API key, or if the provider/budget is unavailable, it explicitly displays **Guided preview** and sample responses. Video uses the existing Runway developer account and supports microphone or typed messages. These are separate conversations; drafts and text history are not transferred to Runway on a handoff.

Guru asks the visitor's preferred first name, then remembers that name and a concise volunteered business goal using `remember_visitor`. Memory is scoped to the Django visitor session and used for up to two hours. A declined name is optional. Returning Guru calls receive the saved context through per-session overrides; the shared avatar never receives private visitor details.

When the visitor agrees to try a demo, `introduce_demo_employee` speaks their name, introduces the selected employee, explains the request and says goodbye. The browser waits for buffered speech and a quiet interval, opens the selected category and confirms Guru's call has ended. A fresh, session-bound handoff connects the employee under the prior call agreement. The employee greets the visitor by name and asks the next relevant question. Tokens expire after ten minutes and can authorize only one successful transfer; the originating call is claimed atomically in the database. No name or request appears in a URL. Direct visitors still agree and press Start.

The selected text demo also receives the introduction context when using its AI gateway. Text history and unsent drafts are not copied into video. Closing or changing categories waits for the current video session to end. Actions are restricted to approved categories, pages and bounded scrolling; the model cannot submit forms.

The call transport publishes one continuous Web Audio input stream. Microphone audio and generated speech for typed messages feed that stream without unpublishing or replacing it between replies. It handles browser audio suspension and reports lost microphone access. Repeated submissions are blocked while a typed message is being delivered; newly typed draft text is preserved, including when delivery cannot finish.

Guru and every category share the same microphone turn handling. The outgoing mic is paused during the opening greeting, assistant speech and a 700ms quiet tail, typed-audio delivery, reconnection and suspended browser audio. Remote speaker events provide a bounded 900ms early hint; actual audio levels sustain the gate so a missing speaker-stop event cannot leave the visitor muted indefinitely. An 80ms mic delay and 25ms level sampling give the speech detector time to close the gate before speaker echo reaches the provider. Echo cancellation, noise suppression and automatic gain control are requested with non-mandatory browser constraints. Quiet voice boost adds 2.5× gain before a compressor to reduce loud peaks; it never bypasses the reply gate. Float audio samples preserve quiet input in the meter, and there is no client-side loudness threshold for sending normal visitor speech. The hardware mic stays captured during normal turn changes, but muting or ending the call stops it. The UI says who is speaking and when it is the visitor's turn. **Interrupt & speak** deliberately opens a short mic window; normal turn protection resumes afterward. This is client-side microphone gating, not an undocumented Runway interruption setting.

Only audio tracks are subscribed; the unused generated face video is not downloaded or decoded. Duplicate notifications for the same audio track do not reattach it or reset playback. Reconnection and pending microphone permission responses are guarded so they cannot reopen a muted or ended call.

Runway's current audio session interface has no native typing event. In Type mode, after the visitor starts typing, a short fixed application speech cue asks the AI to wait silently. It never transmits the unfinished draft. Cues are disabled while the microphone is enabled, throttled, cancelled if obsolete, and sent only after the assistant stops speaking; a timeout never forces a cue into a reply. Character instructions reinforce quiet waiting. Model compliance and provider idle/session limits still apply; typing does not extend Runway's five-minute cap. Guru is also instructed to finish its spoken reply and follow-up before calling the quiet visitor-memory tool.

## Deployment and character maintenance

No new environment variables or database migrations are required beyond the existing video concierge and platform AI configuration. Keep `RUNWAYML_API_SECRET` server-side in Render, using the same developer organization as the public character IDs in `assistant_ai/demo_avatars.json`. That manifest contains no API keys. All 13 entries, including MaryJain, were confirmed READY in Runway on September 16, 2026. Guru's existing avatar ID was retained and its helmet portrait and instructions updated remotely.

The frontend bundle is checked in for the Python-only Render build. Changes remain local until committed and deployed through the usual Git flow. Updating shared Runway character artwork affects that remote character immediately, including any existing deployment using its ID.

```sh
python manage.py sync_demo_characters
python manage.py sync_demo_characters --poll-only
# After correcting a failed character configuration:
python manage.py sync_demo_characters --industry education-community --retry-failed
# Update Guru's portrait only when its artwork changes:
python manage.py sync_guru --helmet
```

`sync_demo_characters` creates missing profiles, updates their instructions and records readiness. It does not start live calls. Portrait changes to an already READY employee require an explicit reference-image update; a normal sync leaves the current portrait alone. Avoid repeatedly provisioning duplicate characters. Run `--poll-only` after processing completes and commit the updated manifest with the feature.

## Verification

September 16, 2026: 125 Django tests and 35 Node tests passed after the microphone cleanup and MaryJain addition. Migration consistency, diff whitespace checks and production static collection passed. Earlier browser checks covered category search, isolated sample chat, desktop and 390×844 layouts, terms display, employee video mounting, and return to text. MaryJain's category, full portrait framing, guided office-hours reply and Type/Speak connection interface were additionally checked in a separate preview tab. No microphone permission or call agreement was accepted during that preview check.

Transport tests cover 20 speech turns beyond two simulated minutes with one mic capture and published stream, speaker echo and gaps between phrases, actual audio-level detection, explicit interruption and recovery, typed-message overlap prevention, stale typing cues, reconnect/duplicate track events, late mic permission, browser audio suspension, and cleanup. Interface tests cover every employee's shared controls and preservation of undelivered drafts. Handoff tests verify confirmed call closure and same-origin/source checks. Physical speaker/microphone quality and mobile Safari remain device checks. The visitor reported missed quiet speech on laptop/desktop speakers with built-in microphones and on phones/tablets; the September 21 changes below address that report.

Live Runway provisioning checks with final settings took 2.89 seconds for Guru and 2.40 seconds for Sage, including the initial defaults lookup. Both test sessions were immediately closed without connecting a visitor. Three decoded frames from the generated gesture clip confirmed the raised hand, presenting sweep and sealed helmet. These timings measure session readiness, not full video playback. Physical microphone use, sustained real conversations and mobile Safari still need device verification. The displayed helmet no longer uses provider facial animation. The local environment has no platform OpenAI key, so the local text preview uses the labelled fallback; OpenAI behavior was tested through a mocked gateway.

Artwork prompts and final asset paths are in [DEMO_ARTWORK.md](DEMO_ARTWORK.md).

MaryJain's personalized Runway session reached READY in 7.37 seconds using a fictional first name and a sample office-hours request. The session was immediately closed without joining a visitor. This verifies session provisioning with introduction context, not a spoken microphone conversation.

## Layout and helmet treatment

The demo overrides the public page width cap and uses a category sidebar plus a portrait/conversation panel. The artwork uses a square frame that preserves its full vertical extent (hat, torso, hands and desk), rather than a wide, shallow video crop. The supplied portraits are seated figures, not full-length standing bodies. On mobile the portrait appears above the conversation. The embedded call reports its content height to the same-origin parent to avoid clipping controls or leaving an oversized empty frame.

Automated coverage includes session isolation, bounded memory, expired and replayed handoffs, provider failure/retry, matching-category context, per-call personalization, CSRF, speech completion and a visitor draft interrupting a pending introduction. Browser checks cover the actual desktop and 390×844 portrait/control layout. Live provisioning tests do not verify a complete spoken conversation or a model's tool-selection accuracy.

Final personalized provisioning checks reached READY in 3.06 seconds for Guru, 2.43 seconds for returning Guru with a saved name, and 2.28 seconds for Sage with a fictional visitor name and reservation request. Each test session was immediately cancelled without joining a visitor. The revised public Guru persona was accepted by Runway. These are provider readiness timings, not end-to-end handoff timings. A browser that blocks automatic audio joining still connects and exposes Hear/Sound controls rather than waiting indefinitely on AudioContext.resume().

## Quiet speech and responsiveness — September 21, 2026

Guru and all 13 demos use the updated transport and Quiet voice boost control. Speak startup reuses the microphone stream acquired after consent instead of stopping and reopening the device. Cancelled or failed startup releases that stream, including late permission responses. Both suspended and Safari-interrupted audio are considered paused and recovery is attempted when the page becomes visible. The 700ms speech tail, 80ms input delay and expiring speaker hint replace the older timing described in historical verification notes.

A completed Guru introduction no longer waits through a second fixed settling delay before handing off. Requests to the site's call endpoints have a 30-second deadline; typed-audio polling requests have a 20-second deadline. These deadlines expose a retryable failure instead of a permanently pending control; they do not speed up Runway generation. Ending a call clears its pending message controls, and a late delivery from that old call cannot change the controls for a new call.

Verification: 136 Django tests and 45 Node tests passed. Coverage includes every employee's shared controls, twenty simulated speech turns, quiet input, stale speaker events, boost without capture restart, Safari interruption recovery, microphone permission/cancellation races, text/voice changes, handoffs and stale delivery results. The transport bundle was rebuilt for the Python-only deployment; syntax, whitespace and production static collection checks passed.

A separate local browser fixture ran the actual transport with real Web Audio nodes and simulated room events, without a hardware microphone or provider connection. A -60 dBFS synthetic input passed through; boost increased its measured outgoing level by 2.48×. A sustained loud boosted signal stayed below clipping in that check (peak 0.945); outgoing signal measured zero during assistant speech even with boost enabled. Cleanup stopped the input track. This verifies the audio graph, not automatic gain support or speech recognition on a customer's device.

Browser checks exercised all 13 category selections, the voice iframe and return to text, and the 390×844 portrait/control layout. No real call, microphone access or agreement acceptance was performed in that UI check. Physical laptop/phone microphones, acoustic echo and recognition in sustained Runway conversations still require device testing. Provider/network latency cannot be eliminated by these client changes. See [MDN's capture constraints](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/autoGainControl) and [iOS interrupted audio behavior](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/state#resuming_interrupted_play_states_in_ios_safari).
