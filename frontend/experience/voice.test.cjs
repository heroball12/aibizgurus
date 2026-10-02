const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(){
  let now=0,tick=null,rms=0,stops=0,captured=[],states=[],errors=[],permissionResolve;
  const track={stop(){stops++;}},stream={getTracks:()=>[track]};
  class FakeAudio{constructor(){this.paused=true;}pause(){this.paused=true;}play(){this.paused=false;return Promise.resolve();}load(){}removeAttribute(){} }
  class Context{constructor(){this.destination={};}resume(){return Promise.resolve();}createMediaElementSource(){return{connect(){}};}createMediaStreamSource(){return{connect(){},disconnect(){}};}createAnalyser(){return{fftSize:1024,frequencyBinCount:128,connect(){},getFloatTimeDomainData(data){data.fill(rms);},getByteFrequencyData(data){data.fill(0);}};} }
  class Recorder{static isTypeSupported(t){return t==='audio/mp4';}constructor(){this.state='inactive';}start(){this.state='recording';}stop(){this.state='inactive';this.ondataavailable({data:new Blob(['a'.repeat(300)])});this.onstop();} }
  const scope={Audio:FakeAudio,AudioContext:Context,MediaRecorder:Recorder,Blob,URL:{createObjectURL:()=>"blob:test",revokeObjectURL(){}},Float32Array,Uint8Array,Math,performance:{now:()=>now},setInterval(fn){tick=fn;return 1;},clearInterval(){tick=null;},requestAnimationFrame(){return 1;},cancelAnimationFrame(){},navigator:{mediaDevices:{getUserMedia:async()=>stream}}};scope.window=scope;
  vm.runInNewContext(fs.readFileSync('static/js/experience-voice.js','utf8'),scope);
  const voice=new scope.ExperienceVoice({onAudio:b=>captured.push(b),onState:(...s)=>states.push(s),onError:e=>errors.push(e),onLevel(){}});
  return{voice,scope,captured,states,errors,stops:()=>stops,advance(ms,volume){rms=volume;for(let n=0;n<ms;n+=60){now+=60;tick?.();}},deferPermission(){scope.navigator.mediaDevices.getUserMedia=()=>new Promise(r=>{permissionResolve=r;});},grant(){permissionResolve(stream);}};
}
test('quiet voices are captured and submitted once after a natural pause',async()=>{const app=setup();await app.voice.listen();app.advance(600,.007);app.advance(1600,0);assert.equal(app.captured.length,1);assert.equal(app.captured[0].type,'audio/mp4');assert.equal(app.voice.recording,false);assert.ok(app.stops()>0);});
test('silence never sends an empty voice turn or keeps microphone running',async()=>{const app=setup();await app.voice.listen();app.advance(12500,0);assert.equal(app.captured.length,0);assert.equal(app.voice.recording,false);});
test('typing/reset cancellation discards partial speech',async()=>{const app=setup();await app.voice.listen();app.advance(900,.02);app.voice.stopCapture(true);assert.equal(app.captured.length,0);assert.equal(app.voice.recording,false);});
test('a delayed permission grant after cancel releases the microphone',async()=>{const app=setup();app.deferPermission();const pending=app.voice.listen();await new Promise(setImmediate);app.voice.stop();app.grant();await pending;assert.equal(app.voice.recording,false);assert.ok(app.stops()>0);});
test('long speech is bounded at 45 seconds',async()=>{const app=setup();await app.voice.listen();app.advance(46000,.012);assert.equal(app.captured.length,1);assert.equal(app.voice.recording,false);});
test('permission denial presents a useful text fallback',async()=>{const app=setup();app.scope.navigator.mediaDevices.getUserMedia=async()=>{const e=new Error();e.name='NotAllowedError';throw e;};await app.voice.listen();assert.match(app.errors[0],/type your message/);assert.equal(app.captured.length,0);});
test('starting playback releases microphone before any spoken output',async()=>{const app=setup();await app.voice.listen();app.advance(900,.01);const playback=app.voice.play({blob:async()=>new Blob(['sound'])});await Promise.resolve();await Promise.resolve();await Promise.resolve();assert.equal(app.voice.recording,false);assert.equal(app.captured.length,0);app.voice.stopPlayback();await playback;});
