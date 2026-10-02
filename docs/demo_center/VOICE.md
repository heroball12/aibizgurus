# Automotive voice

The flagship uses `gpt-4o-mini-transcribe`, the platform's tool-enabled chat model, and `gpt-4o-mini-tts` with the Cedar voice. Existing Guru and Runway voices are unchanged. Axel's sealed helmet stays still; purple light intensity follows the actual output audio analyser rather than animating lips.

## Turn handling

- Browser `getUserMedia`: echo cancellation, noise suppression and automatic gain control.
- MediaRecorder prefers Opus/WebM, with MP4 for compatible Safari devices; no browser speech-recognition service is required.
- Quiet-voice RMS threshold 0.006, minimum 240 ms detected speech, 1.45-second silence endpoint, 45-second maximum utterance and 12-second no-speech timeout. These are starting parameters, not proof of real-room accuracy.
- The microphone is released while transcribing, thinking and speaking; outgoing speaker echo cannot interrupt a reply.
- An explicit Interrupt & speak button stops output before opening the microphone. Typing cancels capture and gives the visitor unlimited drafting time. A new reply is requested only on submission.
- READY / LISTENING / THINKING / SPEAKING and a plain-language hint explain the state. Permission denial, audio playback blocking, unsupported formats, timeout and loss of connection offer typed continuation.
- A generation counter discards late speech after a reset, mode change, interruption or opened dialog. Hiding/leaving the page releases microphone tracks.

Audio POST bodies are bounded to 2 MB and handled in memory, not multipart uploads or media files. The app does not save recordings. Audio is sent to the configured OpenAI service for transcription; successful text transcripts become part of the temporary demo conversation. Provider data handling remains governed by the business's provider configuration.

Server speech bytes are streamed. The current client buffers a short MP3 reply before playing for consistent iPad Safari support; it does not claim streaming playback or sub-second latency. The AI is instructed to answer in 2–4 concise sentences. Tool steps can batch independent calls, are bounded, and are logged by latency. Instrument live latency before choosing another transport or model.

## Configuration and validation

Use existing `PLATFORM_OPENAI_API_KEY` / `OPENAI_API_KEY`. `DEMO_CHAT_MODEL` defaults to the configured platform chat model. No provider key enters browser code. The local environment had no OpenAI key during implementation, so live voice/model accuracy is a deployment/device acceptance check, not an automated-test result.

Check soft and normal voices, noisy showroom conditions, iPad speaker echo, sentence pauses, permission denial, 45-second speech, repeated responses, Type/Speak transitions, interruption and Wi-Fi recovery. Node tests exercise capture lifecycle/quiet-threshold/cancellation with fake browser audio objects; they do not measure a real microphone.

Official implementation references: [function calling](https://developers.openai.com/api/docs/guides/function-calling), [file transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [text to speech](https://developers.openai.com/api/docs/guides/text-to-speech).
