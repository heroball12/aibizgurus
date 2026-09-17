import {Room, RoomEvent, Track, ConnectionState} from 'livekit-client';
import {consumeSession, TranscriptAccumulator, parseClientEvent} from '@runwayml/avatars';

// Publish one stable input track for the whole call. Changing microphone modes or
// sending typed speech never unpublishes it or makes the agent resubscribe.
export async function connectCall({credentials, video, audio, onTranscript, onTool, onState, onVideo, onAudioBlocked, onSpeechLevel=()=>{}, onInputLevel=()=>{}, audioContext:providedContext}) {
  const connection = await consumeSession(credentials);
  const room = new Room({adaptiveStream:false, dynacast:false, disconnectOnPageLeave:true});
  const transcript = new TranscriptAccumulator({interim:true, bufferSize:60});
  const audioContext = providedContext || new AudioContext();
  const inputBus = audioContext.createMediaStreamDestination();
  const inputTrack = inputBus.stream.getAudioTracks()[0];
  // An active zero-gain source keeps the audio graph running in typing mode.
  const silence = audioContext.createOscillator(), silentGain = audioContext.createGain();
  silentGain.gain.value=0; silence.connect(silentGain).connect(inputBus); silence.start();
  const micGain = audioContext.createGain(); micGain.gain.value=0; micGain.connect(inputBus);
  let ended=false, micEnabled=false, micStream=null, micSource=null, playingSource=null;
  let remoteAnalyser=null, remoteSource=null, micAnalyser=null, meterTimer=null, monitorTimer=null;
  let avatarSpeaking=false, heardAvatar=false, lastAvatarSpeech=0, connectedAt=0, queue=Promise.resolve();
  const waveform=new Uint8Array(512);
  function level(analyser){if(!analyser)return 0;analyser.getByteTimeDomainData(waveform);let sum=0;for(const value of waveform)sum+=((value-128)/128)**2;return Math.min(1,Math.sqrt(sum/waveform.length)*5);}
  function attach(track){
    if(track.kind===Track.Kind.Video){track.attach(video);video.play().catch(()=>{});onVideo();}
    else if(track.kind===Track.Kind.Audio){
      track.attach(audio);audio.play().catch(onAudioBlocked);
      remoteSource?.disconnect();remoteAnalyser=audioContext.createAnalyser();remoteAnalyser.fftSize=512;
      remoteSource=audioContext.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));remoteSource.connect(remoteAnalyser);
    }
  }
  transcript.on('update',entries=>onTranscript(entries));
  room.on(RoomEvent.ActiveSpeakersChanged,speakers=>{
    const speaking=speakers.some(participant=>participant.identity!==room.localParticipant.identity);
    if(speaking||avatarSpeaking)lastAvatarSpeech=Date.now();if(speaking)heardAvatar=true;avatarSpeaking=speaking;
  });
  room.on(RoomEvent.TrackSubscribed,attach);
  room.on(RoomEvent.TranscriptionReceived,(segments,participant)=>transcript.ingestNative(segments,participant?.identity||'assistant'));
  room.on(RoomEvent.DataReceived,(payload,participant)=>{const event=parseClientEvent(payload);if(event)onTool(event);else transcript.ingestDataChannel(payload,participant?.identity||'assistant');});
  room.registerTextStreamHandler('lk.transcription',async(reader,participant)=>{let text='';for await(const chunk of reader){text+=chunk;transcript.ingestNative([{id:reader.info.id,text,final:false}],participant.identity);}transcript.ingestNative([{id:reader.info.id,text,final:true}],participant.identity);});
  room.on(RoomEvent.ConnectionStateChanged,state=>{
    if(ended)return;
    if(state===ConnectionState.Reconnecting)onState('reconnecting');
    else if(state===ConnectionState.Connected){
      for(const participant of room.remoteParticipants.values())for(const publication of participant.trackPublications.values())if(publication.track)attach(publication.track);
      onState('active');
    } else if(state===ConnectionState.Disconnected)onState('ended');
  });
  const resume=()=>{if(!ended&&audioContext.state==='suspended')audioContext.resume().catch(()=>onState('audio-paused'));};
  document.addEventListener('visibilitychange',resume);
  try {
    // An automatic same-site handoff may lose transient user activation.
    // Safari can leave resume() pending until a tap; never block joining on it.
    audioContext.resume().catch(onAudioBlocked);
    await room.connect(connection.url,connection.token,{autoSubscribe:true});
    await room.localParticipant.publishTrack(inputTrack,{source:Track.Source.Microphone,name:'conversation-input',dtx:false});
    connectedAt=Date.now();
    meterTimer=setInterval(()=>{const speech=level(remoteAnalyser);if(speech>.025){lastAvatarSpeech=Date.now();heardAvatar=true;}onSpeechLevel(speech);onInputLevel(micEnabled?level(micAnalyser):0);},70);
    monitorTimer=setInterval(resume,5000);
    if(audioContext.state==='suspended')onAudioBlocked();
  } catch(error){document.removeEventListener('visibilitychange',resume);transcript.dispose();silence.stop();await room.disconnect();inputTrack.stop();await audioContext.close();throw error;}
  const api={
    get micEnabled(){return micEnabled;},
    get audioBlocked(){return audioContext.state==='suspended';},
    get avatarSpeaking(){return avatarSpeaking || Date.now()-lastAvatarSpeech<700;},
    async waitForSpeechEnd({shouldContinue=()=>true}={}){
      const started=Date.now(), deadline=started+45000;
      // Tool events can arrive before buffered audio. Allow it to start, then
      // require a quiet interval so the goodbye is not cut off by teardown.
      while(!ended && shouldContinue() && Date.now()<deadline){
        if(Date.now()-started>=1600 && !avatarSpeaking && Date.now()-lastAvatarSpeech>=1200)return true;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      return false;
    },
    async setMic(enabled){
      if(ended||enabled===micEnabled)return;
      await audioContext.resume();
      if(enabled){
        // A device can end without a button click; retire its graph before retrying.
        micSource?.disconnect();micSource=null;micAnalyser=null;
        micStream?.getTracks().forEach(track=>track.stop());micStream=null;
        const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if(ended){stream.getTracks().forEach(track=>track.stop());return;}
        micStream=stream;micSource=audioContext.createMediaStreamSource(stream);micSource.connect(micGain);
        micAnalyser=audioContext.createAnalyser();micAnalyser.fftSize=512;micSource.connect(micAnalyser);
        micEnabled=true;micGain.gain.value=1;
        for(const track of stream.getAudioTracks())track.addEventListener('ended',()=>{if(stream===micStream&&micEnabled&&!ended){micEnabled=false;micGain.gain.value=0;onState('mic-lost');}});
      } else {
        micEnabled=false;micGain.gain.value=0;micSource?.disconnect();micSource=null;micAnalyser=null;
        micStream?.getTracks().forEach(track=>track.stop());micStream=null;onInputLevel(0);
      }
    },
    async unlockAudio(){await audioContext.resume();await room.startAudio();await audio.play();},
    // Serialize normal messages and application typing cues so neither overlaps.
    sendAudio(buffer,{control=false,shouldSend=()=>true}={}){
      const work=async()=>{
        if(ended||!shouldSend())return false;
        if(room.state!==ConnectionState.Connected)throw new Error('The call is reconnecting. Please wait.');
        await audioContext.resume();const decoded=await audioContext.decodeAudioData(buffer.slice(0));
        const deadline=Date.now()+45000;
        while(!ended&&Date.now()<deadline&&(avatarSpeaking||Date.now()-lastAvatarSpeech<800||(!heardAvatar&&Date.now()-connectedAt<14000))){
          if(!shouldSend())return false;
          await new Promise(resolve=>setTimeout(resolve,150));
        }
        if(ended||!shouldSend())return false;
        if(avatarSpeaking){if(control)return false;throw new Error('The assistant is still speaking. Try sending again after the reply.');}
        const source=audioContext.createBufferSource();playingSource=source;source.buffer=decoded;source.connect(inputBus);
        micGain.gain.value=0;
        try{await new Promise(resolve=>{source.onended=resolve;source.start(audioContext.currentTime+.2);});}
        finally{source.disconnect();playingSource=null;if(!ended)micGain.gain.value=micEnabled?1:0;}
        return true;
      };
      const result=queue.then(work,work);queue=result.catch(()=>{});return result;
    },
    async end(){
      if(ended)return;ended=true;clearInterval(meterTimer);clearInterval(monitorTimer);document.removeEventListener('visibilitychange',resume);
      if(playingSource){try{playingSource.stop();}catch(_){}}
      micEnabled=false;micStream?.getTracks().forEach(track=>track.stop());micSource?.disconnect();remoteSource?.disconnect();silence.stop();
      try{await room.localParticipant.publishData(new TextEncoder().encode(JSON.stringify({type:'END_CALL'})),{reliable:true});}catch(_){}
      transcript.dispose();await room.disconnect(true);inputTrack.stop();await audioContext.close();video.srcObject=null;audio.srcObject=null;onSpeechLevel(0);onInputLevel(0);
    },
  };
  return api;
}
