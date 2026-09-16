import {Room, RoomEvent, Track, ConnectionState} from 'livekit-client';
import {consumeSession, TranscriptAccumulator, parseClientEvent} from '@runwayml/avatars';

// Use Runway's credential and event formats with the public LiveKit transport.
// No camera/screen tracks are ever created or published.
export async function connectCall({credentials, video, audio, onTranscript, onTool, onState, onVideo, onAudioBlocked}) {
  const connection = await consumeSession(credentials);
  const room = new Room({adaptiveStream: false, dynacast: false});
  const transcript = new TranscriptAccumulator({interim: true, bufferSize: 40});
  let ended = false, micEnabled = false, playingSource = null;
  let avatarSpeaking = false, heardAvatar = false, lastAvatarSpeech = 0, connectedAt = 0;
  const audioContext = new AudioContext();
  const silentInput = audioContext.createMediaStreamDestination();
  const silentTrack = silentInput.stream.getAudioTracks()[0];
  transcript.on('update', entries => onTranscript(entries));
  room.on(RoomEvent.ActiveSpeakersChanged, speakers => {
    const speaking = speakers.some(participant => participant.identity !== room.localParticipant.identity);
    if(speaking || avatarSpeaking)lastAvatarSpeech=Date.now();
    if(speaking)heardAvatar=true;
    avatarSpeaking=speaking;
  });
  room.on(RoomEvent.TrackSubscribed, track => {
    if (track.kind === Track.Kind.Video) {
      track.attach(video); video.play().catch(() => {}); onVideo();
    } else if (track.kind === Track.Kind.Audio) {
      track.attach(audio); audio.play().catch(onAudioBlocked);
    }
  });
  room.on(RoomEvent.Disconnected, () => onState('ended'));
  room.on(RoomEvent.TranscriptionReceived, (segments, participant) => transcript.ingestNative(segments, participant?.identity || 'assistant'));
  room.on(RoomEvent.DataReceived, (payload, participant) => {
    const event = parseClientEvent(payload);
    if (event) onTool(event);
    else transcript.ingestDataChannel(payload, participant?.identity || 'assistant');
  });
  room.registerTextStreamHandler('lk.transcription', async (reader, participant) => {
    let text = '';
    for await (const chunk of reader) {
      text += chunk;
      transcript.ingestNative([{id: reader.info.id, text, final: false}], participant.identity);
    }
    transcript.ingestNative([{id: reader.info.id, text, final: true}], participant.identity);
  });
  room.on(RoomEvent.ConnectionStateChanged, state => {
    if (state === ConnectionState.Reconnecting) onState('reconnecting');
    else if (state === ConnectionState.Connected) onState('active');
    else if (state === ConnectionState.Disconnected) onState('ended');
  });
  try {
    await room.connect(connection.url, connection.token, {autoSubscribe:true});
    await room.localParticipant.publishTrack(silentTrack, {source:Track.Source.Microphone, name:'typing-mode'});
    connectedAt=Date.now();
  }
  catch (error) { transcript.dispose(); await room.disconnect(); silentTrack.stop(); await audioContext.close(); throw error; }
  return {
    get micEnabled() { return micEnabled; },
    async setMic(enabled) {
      if (ended || enabled===micEnabled) return;
      if (enabled) {
        await room.localParticipant.unpublishTrack(silentTrack, false);
        try { await room.localParticipant.setMicrophoneEnabled(true); micEnabled=true; }
        catch(error){await room.localParticipant.publishTrack(silentTrack,{source:Track.Source.Microphone,name:'typing-mode'});throw error;}
      } else {
        await room.localParticipant.setMicrophoneEnabled(false);
        const real=room.localParticipant.getTrackPublication(Track.Source.Microphone)?.track;
        if(real)await room.localParticipant.unpublishTrack(real,true);
        await room.localParticipant.publishTrack(silentTrack,{source:Track.Source.Microphone,name:'typing-mode'});
        micEnabled=false;
      }
    },
    async unlockAudio() { await audioContext.resume(); },
    async sendAudio(buffer) {
      if (ended || room.state !== ConnectionState.Connected) throw new Error('Call is not connected.');
      await audioContext.resume();
      const decoded = await audioContext.decodeAudioData(buffer);
      // Queue typed input until a pause, including the initial greeting. Sending
      // synthetic speech over the greeting can be dropped by the native agent.
      const deadline=Date.now()+18000;
      while(!ended && Date.now()<deadline && (avatarSpeaking || Date.now()-lastAvatarSpeech<1000 || (!heardAvatar && Date.now()-connectedAt<12000))) {
        await new Promise(resolve=>setTimeout(resolve,120));
      }
      if (ended) return;
      const restoreMic = micEnabled;
      if (restoreMic) await this.setMic(false);
      const source = audioContext.createBufferSource();
      playingSource = source;
      source.buffer = decoded;
      source.connect(silentInput);
      try {
        await new Promise(resolve => { source.onended=resolve; source.start(audioContext.currentTime+0.3); });
      } finally {
        source.disconnect(); playingSource=null;
        if (restoreMic && !ended) await this.setMic(true);
      }
    },
    async end() {
      if (ended) return;
      ended = true;
      if(playingSource) { try { playingSource.stop(); } catch (_) {} }
      try { await room.localParticipant.publishData(new TextEncoder().encode(JSON.stringify({type: 'END_CALL'})), {reliable: true}); } catch (_) { /* HTTP cancellation is also sent by the caller. */ }
      transcript.dispose();
      await room.disconnect(true);
      silentTrack.stop(); await audioContext.close();
      video.srcObject = null; audio.srcObject = null;
    },
  };
}
