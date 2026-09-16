# Category demo center

The demo page groups the 101 catalog industries into 12 video employees. Search matches both the category and every underlying industry. Each category has its own chat history, sample business, suggested questions and character. These demonstrations never create real appointments, orders, leads or service requests.

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
| Fitness & movement | Rio | Athletic jacket |
| Education & community | Mira | Cardigan, bob and violet hair clip |
| Pet services | Kai | Veterinary scrubs |
| Transport & logistics | Jett | Reflective vest and ponytail |

All portraits use sealed graphite helmets with a purple visor and gold details. The site adds a purple speech glow driven by the actual remote audio level. Runway renders the live video from these portraits; it does not expose a lip-animation switch or precise live hand choreography. The generated Guru gesture clip is a short visual transition played over the live video when a website action occurs; live audio continues. Reduced-motion preferences suppress that clip.

## Conversations and handoffs

Text chat uses the existing platform OpenAI gateway. Without its configured API key, or if the provider/budget is unavailable, it explicitly displays **Guided preview** and sample responses. Video uses the existing Runway developer account and supports microphone or typed messages. These are separate conversations; drafts and text history are not transferred to Runway on a handoff.

Guru's `introduce_demo_employee` tool opens the matching category after a spoken introduction and next step. The visitor chooses whether to try text or video. Choosing employee video closes Guru's call before another employee can connect. Closing or changing categories similarly waits for the current video session to end. New calls still require the visitor's agreement and Start conversation. Actions are restricted to approved categories, pages and bounded scrolling; the model cannot submit forms.

The call transport publishes one continuous Web Audio input stream. Microphone audio and generated speech for typed messages feed that stream without unpublishing or replacing it between replies. It handles browser audio suspension and reports lost microphone access. Repeated submissions are blocked while a typed message is being delivered; newly typed draft text is preserved.

Runway's current audio session interface has no native typing event. After the visitor starts typing, a short fixed application speech cue asks the AI to wait silently. It never transmits the unfinished draft. Cues are throttled, cancelled if obsolete, and sent after the assistant stops speaking. Character instructions reinforce quiet waiting. Model compliance and provider idle/session limits still apply; typing does not extend Runway's five-minute cap.

## Deployment and character maintenance

No new environment variables or database migrations are required beyond the existing video concierge and platform AI configuration. Keep `RUNWAYML_API_SECRET` server-side in Render, using the same developer organization as the public character IDs in `assistant_ai/demo_avatars.json`. That manifest contains no API keys. All 12 entries were confirmed READY in Runway on September 16, 2026. Guru's existing avatar ID was retained and its helmet portrait and instructions updated remotely.

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

September 16, 2026: 111 Django tests and 17 Node tests passed. Migration consistency and production static collection passed. Browser checks covered category search, isolated sample chat, desktop and 390×844 layouts, terms display, employee video mounting, and return to text. Transport tests cover repeated voice/text changes beyond one simulated minute, mic loss/recovery, denied permission, stale typing cues, browser audio suspension, and cleanup. Handoff tests verify confirmed call closure and same-origin/source checks.

Live Runway provisioning checks with final settings took 2.89 seconds for Guru and 2.40 seconds for Sage, including the initial defaults lookup. Both test sessions were immediately closed without connecting a visitor. Three decoded frames from the generated gesture clip confirmed the raised hand, presenting sweep and sealed helmet. These timings measure session readiness, not full video playback. Physical microphone use, sustained real conversations, exact live visor animation and mobile Safari still need device verification. The local environment has no platform OpenAI key, so the local text preview uses the labelled fallback; OpenAI behavior was tested through a mocked gateway.

Artwork prompts and final asset paths are in [DEMO_ARTWORK.md](DEMO_ARTWORK.md).
