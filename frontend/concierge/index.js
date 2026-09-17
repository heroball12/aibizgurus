import {Room, RoomEvent, Track, ConnectionState} from 'livekit-client';
import {consumeSession, TranscriptAccumulator, parseClientEvent} from '@runwayml/avatars';

// One published input for the whole call. The microphone gate prevents speaker
// bleed from being interpreted as a visitor interrupting the assistant.
const SPEECH_TAIL_MS = 1100;
const OPENING_WAIT_MS = 14000;
export async function connectCall({credentials, video, audio, onTranscript, onTool, onState, onMediaReady=()=>{}, onAudioBlocked, onSpeechLevel=()=>{}, onInputLevel=()=>{}, onListeningState=()=>{}, audioContext:providedContext}) {
  const connection = await consumeSession(credentials);
  const room = new Room({adaptiveStream:false, dynacast:false, disconnectOnPageLeave:true});
  const transcript = new TranscriptAccumulator({interim:true, bufferSize:60});
  const audioContext = providedContext || new AudioContext({latencyHint:'interactive'});
  const inputBus = audioContext.createMediaStreamDestination();
  const inputTrack = inputBus.stream.getAudioTracks()[0];
  const silence = audioContext.createOscillator(), silentGain = audioContext.createGain();
  silentGain.gain.value=0; silence.connect(silentGain).connect(inputBus); silence.start();
  const micGain = audioContext.createGain(); micGain.gain.value=0; micGain.connect(inputBus);
  // Give incoming speech detection a head start on acoustic speaker echo.
  const micDelay = audioContext.createDelay(.5); micDelay.delayTime.value=.15; micDelay.connect(micGain);
  let ended=false, micEnabled=false, micStream=null, micSource=null, playingSource=null, micVersion=0, micPending=false;
  let remoteAnalyser=null, remoteSource=null, remoteTrack=null, remoteMediaTrack=null, micAnalyser=null, meterTimer=null, monitorTimer=null;
  let avatarSpeaking=false, heardAvatar=false, lastAvatarSpeech=0, connectedAt=0, queue=Promise.resolve();
  let listeningState='muted', interruptUntil=0, interruptStarted=0, interruptHeardVoice=false, lastInterruptVoice=0;
  const waveform=new Uint8Array(512);
  function level(analyser){if(!analyser)return 0;analyser.getByteTimeDomainData(waveform);let sum=0;for(const value of waveform)sum+=((value-128)/128)**2;return Math.min(1,Math.sqrt(sum/waveform.length)*5);}
  function avatarBusy(){return avatarSpeaking || (heardAvatar && Date.now()-lastAvatarSpeech<SPEECH_TAIL_MS);}
  function waitingForOpening(){return !heardAvatar && Date.now()-connectedAt<OPENING_WAIT_MS;}
  function updateInput() {
    const now=Date.now(), micLevel=micEnabled?level(micAnalyser):0;
    if(interruptUntil){
      if(micLevel>.06){interruptHeardVoice=true;lastInterruptVoice=now;}
      if(now>=interruptUntil || (interruptHeardVoice && now-lastInterruptVoice>1200) || (!avatarBusy() && now-interruptStarted>1600))interruptUntil=0;
    }
    let next='muted';
    if(!ended && micEnabled){
      if(room.state!==ConnectionState.Connected || !remoteTrack)next='reconnecting';
      else if(audioContext.state!=='running')next='audio-paused';
      else if(playingSource)next='sending';
      else if(interruptUntil)next='listening';
      else if(avatarBusy())next='assistant-speaking';
      else if(waitingForOpening())next='waiting';
      else next='listening';
    }
    micGain.gain.value=next==='listening'?1:0;
    onInputLevel(next==='listening'?micLevel:0);
    if(next!==listeningState){listeningState=next;onListeningState(next);}
  }
  function detachRemote(track) {
    if(track!==remoteTrack)return;
    track.detach(audio);remoteSource?.disconnect();remoteSource=null;remoteAnalyser=null;remoteTrack=null;remoteMediaTrack=null;
    avatarSpeaking=false;onSpeechLevel(0);updateInput();
  }
  function attach(track) {
    if(ended || track.kind!==Track.Kind.Audio)return;
    // Connected/reconnected and TrackSubscribed can report the same track.
    // Reattaching it resets playback and can sound like a clipped syllable.
    if(track===remoteTrack && track.mediaStreamTrack===remoteMediaTrack)return;
    if(remoteTrack)detachRemote(remoteTrack);
    remoteTrack=track;remoteMediaTrack=track.mediaStreamTrack;
    track.attach(audio);audio.play().catch(onAudioBlocked);
    remoteAnalyser=audioContext.createAnalyser();remoteAnalyser.fftSize=512;
    remoteSource=audioContext.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));remoteSource.connect(remoteAnalyser);
    onMediaReady();updateInput();
  }
  function subscribe(publication) {
    // The website displays sealed-helmet artwork. Do not download/decode the
    // unused generated video, especially on phones or weaker connections.
    publication.setSubscribed(publication.kind===Track.Kind.Audio);
    if(publication.track)attach(publication.track);
  }
  function subscribeExisting(){for(const participant of room.remoteParticipants.values())for(const publication of participant.trackPublications.values())subscribe(publication);}
  transcript.on('update',entries=>onTranscript(entries));
  room.on(RoomEvent.ActiveSpeakersChanged,speakers=>{
    const speaking=speakers.some(participant=>participant.identity!==room.localParticipant.identity);
    if(speaking||avatarSpeaking)lastAvatarSpeech=Date.now();if(speaking)heardAvatar=true;avatarSpeaking=speaking;updateInput();
  });
  room.on(RoomEvent.TrackPublished,subscribe);
  room.on(RoomEvent.TrackSubscribed,attach);
  room.on(RoomEvent.TrackUnsubscribed,detachRemote);
  room.on(RoomEvent.TranscriptionReceived,(segments,participant)=>transcript.ingestNative(segments,participant?.identity||'assistant'));
  room.on(RoomEvent.DataReceived,(payload,participant)=>{const event=parseClientEvent(payload);if(event)onTool(event);else transcript.ingestDataChannel(payload,participant?.identity||'assistant');});
  room.registerTextStreamHandler('lk.transcription',async(reader,participant)=>{let text='';for await(const chunk of reader){text+=chunk;transcript.ingestNative([{id:reader.info.id,text,final:false}],participant.identity);}transcript.ingestNative([{id:reader.info.id,text,final:true}],participant.identity);});
  room.on(RoomEvent.ConnectionStateChanged,state=>{
    if(ended)return;
    if(state===ConnectionState.Reconnecting){interruptUntil=0;updateInput();onState('reconnecting');}
    else if(state===ConnectionState.Connected){subscribeExisting();updateInput();onState('active');}
    else if(state===ConnectionState.Disconnected){updateInput();onState('ended');}
  });
  const resume=()=>{if(!ended&&audioContext.state==='suspended')audioContext.resume().then(updateInput).catch(()=>onState('audio-paused'));};
  document.addEventListener('visibilitychange',resume);
  try {
    // A transferred call may need a tap before audio can resume. Joining must
    // not wait forever for the browser's user-activation policy.
    audioContext.resume().catch(onAudioBlocked);
    await room.connect(connection.url,connection.token,{autoSubscribe:false});
    subscribeExisting();
    await room.localParticipant.publishTrack(inputTrack,{source:Track.Source.Microphone,name:'conversation-input',dtx:false});
    connectedAt=Date.now();
    meterTimer=setInterval(()=>{
      const speech=level(remoteAnalyser);
      if(speech>.025){lastAvatarSpeech=Date.now();heardAvatar=true;}
      onSpeechLevel(speech);updateInput();
    },50);
    monitorTimer=setInterval(resume,5000);
    if(audioContext.state==='suspended')onAudioBlocked();
  } catch(error){
    ended=true;document.removeEventListener('visibilitychange',resume);transcript.dispose();silence.stop();remoteSource?.disconnect();
    try{await room.disconnect();}finally{inputTrack.stop();await audioContext.close();}
    throw error;
  }
  const api={
    get micEnabled(){return micEnabled;},
    get audioBlocked(){return audioContext.state==='suspended';},
    get avatarSpeaking(){return avatarBusy();},
    get listeningState(){return listeningState;},
    async waitForSpeechEnd({shouldContinue=()=>true}={}){
      const started=Date.now(), deadline=started+45000;
      while(!ended && shouldContinue() && Date.now()<deadline){
        if(Date.now()-started>=1600 && !avatarBusy() && !waitingForOpening())return true;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      return false;
    },
    async setMic(enabled){
      if(ended || (enabled===micEnabled && !micPending))return;
      const version=++micVersion;micPending=enabled;interruptUntil=0;
      micEnabled=false;micSource?.disconnect();micSource=null;micAnalyser=null;
      micStream?.getTracks().forEach(track=>track.stop());micStream=null;updateInput();
      if(!enabled)return;
      try {
        await audioContext.resume();
        if(ended || version!==micVersion)return;
        const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:false,channelCount:1},video:false});
        if(ended || version!==micVersion){stream.getTracks().forEach(track=>track.stop());return;}
        micStream=stream;micSource=audioContext.createMediaStreamSource(stream);micSource.connect(micDelay);
        micAnalyser=audioContext.createAnalyser();micAnalyser.fftSize=512;micSource.connect(micAnalyser);
        micEnabled=true;updateInput();
        for(const track of stream.getAudioTracks())track.addEventListener('ended',()=>{if(stream===micStream&&micEnabled&&!ended){micEnabled=false;interruptUntil=0;updateInput();onState('mic-lost');}});
      } finally {if(version===micVersion)micPending=false;}
    },
    async interrupt(){
      if(ended || !micEnabled || playingSource || room.state!==ConnectionState.Connected)return false;
      await audioContext.resume();
      if(ended || !micEnabled)return false;
      interruptStarted=Date.now();interruptUntil=interruptStarted+6000;interruptHeardVoice=false;
      updateInput();return true;
    },
    async unlockAudio(){await audioContext.resume();await room.startAudio();await audio.play();updateInput();},
    sendAudio(buffer,{control=false,shouldSend=()=>true}={}){
      const allowed=()=>!ended && shouldSend() && !(control && micEnabled);
      const work=async()=>{
        if(!allowed())return false;
        if(room.state!==ConnectionState.Connected)throw new Error('The call is reconnecting. Please wait.');
        await audioContext.resume();const decoded=await audioContext.decodeAudioData(buffer.slice(0));
        const deadline=Date.now()+45000;
        while(allowed() && Date.now()<deadline && (avatarBusy() || waitingForOpening()))await new Promise(resolve=>setTimeout(resolve,100));
        if(!allowed())return false;
        if(avatarBusy() || waitingForOpening()){
          if(control)return false;
          throw new Error('The assistant is still speaking. Try sending again after the reply.');
        }
        if(room.state!==ConnectionState.Connected)throw new Error('The call is reconnecting. Please wait.');
        const source=audioContext.createBufferSource();playingSource=source;source.buffer=decoded;source.connect(inputBus);updateInput();
        try{await new Promise(resolve=>{source.onended=resolve;source.start();});}
        finally{source.disconnect();if(playingSource===source)playingSource=null;updateInput();}
        return !ended;
      };
      const result=queue.then(work,work);queue=result.catch(()=>{});return result;
    },
    async end(){
      if(ended)return;ended=true;++micVersion;micPending=false;interruptUntil=0;
      clearInterval(meterTimer);clearInterval(monitorTimer);document.removeEventListener('visibilitychange',resume);
      if(playingSource){try{playingSource.stop();}catch(_){}}
      micEnabled=false;updateInput();micStream?.getTracks().forEach(track=>track.stop());micSource?.disconnect();remoteSource?.disconnect();micDelay.disconnect();silence.stop();
      try{await room.localParticipant.publishData(new TextEncoder().encode(JSON.stringify({type:'END_CALL'})),{reliable:true});}catch(_){}
      transcript.dispose();
      try{await room.disconnect(true);}finally{inputTrack.stop();await audioContext.close();if(video)video.srcObject=null;audio.srcObject=null;onSpeechLevel(0);onInputLevel(0);}
    },
  };
  return api;
}
