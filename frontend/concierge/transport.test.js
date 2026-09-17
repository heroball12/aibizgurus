import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Run the real transport against deterministic media devices and a simulated room.
function fixture() {
  let now=100000, permission, room, holdPlayback=false;
  const tracks=[], sources=[], published=[], states=[], inputStates=[], timers=new Map(), listeners=new Map(), gains=[], analysers=[], buffers=[], constraints=[];
  const track=()=>{const item={stopped:false,events:{},stop(){this.stopped=true;},addEventListener(k,fn){this.events[k]=fn;}};tracks.push(item);return item;};
  const input=track();
  const stream=t=>({isMic:true,getAudioTracks:()=>[t],getTracks:()=>[t]});
  const node=()=>({gain:{value:0},delayTime:{value:0},sample:128,connect(target){return target;},disconnect(){this.disconnected=true;},start(){},stop(){this.onended?.();},getByteTimeDomainData(data){data.fill(this.sample);}});
  const ctx={state:'suspended',currentTime:0,resume:async()=>{ctx.state='running';},close:async()=>{ctx.state='closed';},
    createMediaStreamDestination:()=>({stream:stream(input)}),createOscillator:node,createDelay:node,
    createGain:()=>{const result=node();gains.push(result);return result;},createAnalyser:()=>{const result=node();analysers.push(result);return result;},
    createMediaStreamSource:media=>{const source=node();source.isMic=media.isMic;sources.push(source);return source;},
    decodeAudioData:async()=>({duration:.5}),createBufferSource:()=>{const source=node();source.start=()=>{if(!holdPlayback)queueMicrotask(()=>source.onended?.());};buffers.push(source);return source;}};
  const remote=()=>({kind:'audio',mediaStreamTrack:{},attachments:0,detachments:0,attach(){this.attachments++;},detach(){this.detachments++;}});
  const remoteAudio=remote();
  const publication=(kind,media=null)=>({kind,track:media,requests:[],setSubscribed(enabled){this.requests.push(enabled);if(enabled && !this.delivered){this.delivered=true;room.events.track(this.track);}}});
  const audioPublication=publication('audio',remoteAudio),videoPublication=publication('video');
  class FakeRoom {
    constructor(){room=this;this.events={};this.remoteParticipants=new Map([['assistant',{trackPublications:new Map([['audio',audioPublication],['video',videoPublication]])}]]);this.localParticipant={identity:'visitor',publishTrack:async t=>published.push(t),publishData:async()=>{}};}
    on(type,fn){this.events[type]=fn;return this;}
    registerTextStreamHandler(){}
    async connect(url,token,options){this.options=options;this.state='connected';this.events.state('connected');}
    async disconnect(){this.state='disconnected';this.events.state('disconnected');}
    async startAudio(){}
  }
  const tick=()=>timers.get(50)?.();
  const context=vm.createContext({Room:FakeRoom,RoomEvent:{ActiveSpeakersChanged:'speakers',TrackPublished:'published',TrackSubscribed:'track',TrackUnsubscribed:'unsubscribed',TranscriptionReceived:'transcription',DataReceived:'data',ConnectionStateChanged:'state'},Track:{Kind:{Video:'video',Audio:'audio'},Source:{Microphone:'microphone'}},ConnectionState:{Connected:'connected',Reconnecting:'reconnecting',Disconnected:'disconnected'},
    consumeSession:async()=>({url:'wss://example.test',token:'test'}),TranscriptAccumulator:class {on(){}dispose(){}},parseClientEvent:()=>null,
    AudioContext:class {constructor(){return ctx;}},MediaStream:class{},TextEncoder,Uint8Array,Date:{now:()=>now},
    navigator:{mediaDevices:{getUserMedia:async options=>{constraints.push(options);return permission?permission():stream(track());}}},
    document:{addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key)},
    setInterval:(fn,ms)=>{timers.set(ms,fn);return ms;},clearInterval:id=>timers.delete(id),
    setTimeout:(fn,ms)=>{now+=ms;tick();queueMicrotask(fn);},
  });
  const source=readFileSync(new URL('./index.js',import.meta.url),'utf8').replace(/^import .*\n/gm,'').replace('export async function connectCall','async function connectCall');
  vm.runInContext(source,context);
  context.args={credentials:{},audioContext:ctx,video:{play:async()=>{}},audio:{play:async()=>{}},onTranscript(){},onTool(){},onState:s=>states.push(s),onListeningState:s=>inputStates.push(s),onAudioBlocked(){}};
  return {connect:()=>vm.runInContext('connectCall(args)',context),tracks,sources,published,states,inputStates,timers,listeners,ctx,input,buffers,constraints,remoteAudio,audioPublication,videoPublication,
    gate:()=>gains[1].gain.value,room:()=>room,remote,holdPlayback:()=>{holdPlayback=true;},
    remoteLevel:value=>{analysers[0].sample=value;tick();},
    setPermission:fn=>{permission=fn;},makeStream:()=>stream(track()),
    speakers:list=>room.events.speakers(list),now:()=>now,advance:ms=>{now+=ms;tick();},
    deny:()=>{permission=async()=>{throw new Error('Permission denied');};}};
}

test('voice and typed replies retain one live input through repeated mode changes beyond a minute',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);
  for(let turn=0;turn<8;turn++){
    await call.setMic(true);assert.equal(call.micEnabled,true);
    assert.equal(await call.sendAudio(new ArrayBuffer(10)),true);
    assert.equal(call.micEnabled,true);
    await call.setMic(false);f.advance(10000);
  }
  assert.equal(f.published.length,1);assert.equal(f.published[0],f.input);assert.equal(f.input.stopped,false);
  assert.ok(f.tracks.slice(1).every(t=>t.stopped));
  await call.end();assert.equal(f.input.stopped,true);assert.equal(f.ctx.state,'closed');assert.equal(f.timers.size,0);
  assert.equal(await call.sendAudio(new ArrayBuffer(10)),false);
});

test('lost microphone can be reacquired without leaving the previous source attached',async()=>{
  const f=fixture(),call=await f.connect();await call.setMic(true);
  f.tracks[1].events.ended();assert.equal(call.micEnabled,false);assert.ok(f.states.includes('mic-lost'));
  await call.setMic(true);assert.equal(f.sources.find(s=>s.isMic).disconnected,true);assert.equal(f.tracks[1].stopped,true);
  f.tracks[1].events.ended();assert.equal(call.micEnabled,true,'a stale device event cannot mute the new mic');
  assert.equal(f.published.length,1);await call.end();
});

test('typing remains available after denied microphone access and a stale typing cue is dropped',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);f.deny();
  await assert.rejects(call.setMic(true),/Permission denied/);
  assert.equal(await call.sendAudio(new ArrayBuffer(10),{control:true,shouldSend:()=>false}),false);
  assert.equal(await call.sendAudio(new ArrayBuffer(10)),true);assert.equal(f.input.stopped,false);await call.end();
});

test('browser suspension resumes without republishing input and cleanup removes recovery listeners',async()=>{
  const f=fixture(),call=await f.connect();f.ctx.state='suspended';f.listeners.get('visibilitychange')();
  assert.equal(f.ctx.state,'running');assert.equal(f.published.length,1);await call.end();assert.equal(f.listeners.size,0);
});


test('handoff waits through the goodbye and a quiet interval, and aborts on visitor activity',async()=>{
  const f=fixture(),call=await f.connect();
  f.speakers([{identity:'assistant'}]);let checks=0, speechEnded=0;const started=f.now();
  assert.equal(await call.waitForSpeechEnd({shouldContinue:()=>{if(++checks===20){f.speakers([]);speechEnded=f.now();}return true;}}),true);
  assert.ok(f.now()-started>=1600,'allow buffered audio to start');
  assert.ok(f.now()-speechEnded>=1100,'do not cut the goodbye before the audio tail clears');
  assert.equal(await call.waitForSpeechEnd({shouldContinue:()=>false}),false);
  await call.end();assert.equal(await call.waitForSpeechEnd(),false);
});

test('blocked autoplay does not leave a transferred call stuck connecting',async()=>{
  const f=fixture();f.ctx.resume=()=>new Promise(()=>{});
  const call=await f.connect();
  assert.equal(call.audioBlocked,true);assert.equal(f.published.length,1);
  await call.end();
});


test('speaker echo cannot interrupt the greeting or gaps between reply phrases',async()=>{
  const f=fixture(),call=await f.connect();await call.setMic(true);
  assert.equal(f.gate(),0);assert.equal(call.listeningState,'waiting');
  f.speakers([{identity:'assistant'}]);assert.equal(f.gate(),0);
  f.speakers([]);f.advance(350);assert.equal(f.gate(),0,'keep the mic paused between phrases');
  f.speakers([{identity:'assistant'}]);f.advance(500);assert.equal(f.gate(),0);
  f.speakers([]);f.advance(1200);assert.equal(f.gate(),1);assert.equal(call.listeningState,'listening');
  assert.equal(call.micEnabled,true);assert.equal(f.constraints[0].audio.echoCancellation,true);
  assert.equal(f.constraints[0].audio.autoGainControl,false);await call.end();
});

test('audio-level detection protects replies even if speaker events arrive late',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);await call.setMic(true);assert.equal(f.gate(),1);
  f.remoteLevel(145);assert.equal(f.gate(),0);assert.equal(call.listeningState,'assistant-speaking');
  f.remoteLevel(128);f.advance(1200);assert.equal(f.gate(),1);await call.end();
});

test('twenty speech turns keep one mic capture and resume listening after every reply',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);await call.setMic(true);
  for(let turn=0;turn<20;turn++){
    f.speakers([{identity:'assistant'}]);f.advance(3500);assert.equal(f.gate(),0);
    f.speakers([]);f.advance(1200);assert.equal(f.gate(),1);f.advance(2000);
  }
  assert.equal(f.published.length,1);assert.equal(f.constraints.length,1);
  assert.equal(f.tracks[1].stopped,false);assert.equal(f.remoteAudio.attachments,1);await call.end();
});

test('intentional interruption opens the mic briefly and cannot leave protection disabled',async()=>{
  const f=fixture(),call=await f.connect();await call.setMic(true);f.speakers([{identity:'assistant'}]);
  assert.equal(await call.interrupt(),true);assert.equal(f.gate(),1);
  f.advance(6100);assert.equal(f.gate(),0);assert.equal(call.micEnabled,true);
  await call.setMic(false);assert.equal(await call.interrupt(),false);await call.end();
});

test('typing notifications never inject artificial speech into microphone conversations',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);await call.setMic(true);
  assert.equal(await call.sendAudio(new ArrayBuffer(10),{control:true}),false);assert.equal(f.buffers.length,0);
  await call.end();
});

test('typed audio does not reopen the microphone over an assistant reply',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);await call.setMic(true);f.holdPlayback();
  const sent=call.sendAudio(new ArrayBuffer(10));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.gate(),0);assert.equal(call.listeningState,'sending');
  f.speakers([{identity:'assistant'}]);f.buffers[0].onended();assert.equal(await sent,true);
  assert.equal(f.gate(),0,'source cleanup must preserve the reply gate');await call.end();
});

test('a typing cue or typed message times out without cutting into ongoing speech',async()=>{
  const f=fixture(),call=await f.connect();f.speakers([{identity:'assistant'}]);
  assert.equal(await call.sendAudio(new ArrayBuffer(10),{control:true}),false);
  await assert.rejects(call.sendAudio(new ArrayBuffer(10)),/still speaking/);
  assert.equal(f.buffers.length,0);await call.end();
});

test('audio-only subscription and reconnects do not repeatedly attach or restart playback',async()=>{
  const f=fixture(),call=await f.connect();f.advance(16000);await call.setMic(true);
  assert.equal(f.room().options.autoSubscribe,false);assert.ok(f.videoPublication.requests.every(v=>v===false));
  for(let i=0;i<4;i++){
    f.room().state='reconnecting';f.room().events.state('reconnecting');assert.equal(f.gate(),0);
    f.room().state='connected';f.room().events.state('connected');f.room().events.track(f.remoteAudio);
  }
  assert.equal(f.remoteAudio.attachments,1);assert.equal(f.sources.filter(s=>!s.isMic).length,1);
  f.room().events.unsubscribed(f.remoteAudio);assert.equal(f.gate(),0);
  const replacement=f.remote();f.room().events.track(replacement);assert.equal(replacement.attachments,1);
  assert.equal(f.remoteAudio.detachments,1);assert.equal(f.gate(),1);await call.end();
});

test('muting while microphone permission is pending prevents a late microphone activation',async()=>{
  const f=fixture(),call=await f.connect();let allow;
  f.setPermission(()=>new Promise(resolve=>{allow=resolve;}));const enable=call.setMic(true);
  await new Promise(resolve=>setImmediate(resolve));await call.setMic(false);
  const late=f.makeStream();allow(late);await enable;
  assert.equal(call.micEnabled,false);assert.equal(f.gate(),0);assert.equal(late.getTracks()[0].stopped,true);await call.end();
});
