import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Run the real transport against deterministic media devices and a simulated room.
function fixture() {
  let now=100000, permission;
  const tracks=[], sources=[], published=[], states=[], timers=new Map(), listeners=new Map();
  const track=()=>{const item={stopped:false,events:{},stop(){this.stopped=true;},addEventListener(k,fn){this.events[k]=fn;}};tracks.push(item);return item;};
  const input=track();
  const stream=t=>({getAudioTracks:()=>[t],getTracks:()=>[t]});
  const node=()=>({gain:{value:0},connect(target){return target;},disconnect(){this.disconnected=true;},start(){},stop(){this.onended?.();},getByteTimeDomainData(data){data.fill(128);}});
  const ctx={state:'suspended',currentTime:0,resume:async()=>{ctx.state='running';},close:async()=>{ctx.state='closed';},
    createMediaStreamDestination:()=>({stream:stream(input)}),createOscillator:node,createGain:node,createAnalyser:node,
    createMediaStreamSource:()=>{const source=node();sources.push(source);return source;},
    decodeAudioData:async()=>({duration:.5}),createBufferSource:()=>{const source=node();source.start=()=>queueMicrotask(()=>source.onended?.());return source;}};
  class FakeRoom {
    constructor(){this.events={};this.remoteParticipants=new Map();this.localParticipant={identity:'visitor',publishTrack:async t=>published.push(t),publishData:async()=>{}};}
    on(type,fn){this.events[type]=fn;return this;}
    registerTextStreamHandler(){}
    async connect(){this.state='connected';this.events.state('connected');}
    async disconnect(){this.state='disconnected';this.events.state('disconnected');}
    async startAudio(){}
  }
  const context=vm.createContext({Room:FakeRoom,RoomEvent:{ActiveSpeakersChanged:'speakers',TrackSubscribed:'track',TranscriptionReceived:'transcription',DataReceived:'data',ConnectionStateChanged:'state'},Track:{Kind:{Video:'video',Audio:'audio'},Source:{Microphone:'microphone'}},ConnectionState:{Connected:'connected',Reconnecting:'reconnecting',Disconnected:'disconnected'},
    consumeSession:async()=>({url:'wss://example.test',token:'test'}),TranscriptAccumulator:class {on(){}dispose(){}},parseClientEvent:()=>null,
    AudioContext:class {constructor(){return ctx;}},MediaStream:class{},TextEncoder,Uint8Array,Date:{now:()=>now},
    navigator:{mediaDevices:{getUserMedia:async()=>permission?permission():stream(track())}},
    document:{addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key)},
    setInterval:(fn,ms)=>{timers.set(ms,fn);return ms;},clearInterval:id=>timers.delete(id),
    setTimeout:fn=>{now+=150;queueMicrotask(fn);},
  });
  const source=readFileSync(new URL('./index.js',import.meta.url),'utf8').replace(/^import .*\n/gm,'').replace('export async function connectCall','async function connectCall');
  vm.runInContext(source,context);
  context.args={credentials:{},audioContext:ctx,video:{play:async()=>{}},audio:{play:async()=>{}},onTranscript(){},onTool(){},onState:s=>states.push(s),onVideo(){},onAudioBlocked(){}};
  return {connect:()=>vm.runInContext('connectCall(args)',context),tracks,sources,published,states,timers,listeners,ctx,input,
    advance:ms=>{now+=ms;},deny:()=>{permission=async()=>{throw new Error('Permission denied');};}};
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
  await call.setMic(true);assert.equal(f.sources[0].disconnected,true);assert.equal(f.tracks[1].stopped,true);
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
