/* Bounded microphone turns: echo protection, quiet-voice support and explicit interruption.
   Audio exists in memory only; no storage, speech-recognition vendor or browser transcript cache. */
(function (root) {
  'use strict';
  class ExperienceVoice {
    constructor({onAudio, onState, onError, onLevel}) {
      Object.assign(this, {onAudio, onState, onError, onLevel});
      this.captureId = 0; this.playId = 0; this.recording = false;
      this.audio = new Audio(); this.audio.preload = 'auto';
    }
    async unlock() {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) throw new Error('Voice is not supported in this browser. You can type instead.');
      this.context ||= new Context();
      await this.context.resume();
      if (!this.output) {
        this.output = this.context.createMediaElementSource(this.audio);
        this.speakerMeter = this.context.createAnalyser(); this.speakerMeter.fftSize = 256;
        this.output.connect(this.speakerMeter); this.speakerMeter.connect(this.context.destination);
      }
    }
    async listen() {
      this.stopCapture(true); this.stopPlayback();
      const ticket = ++this.captureId;
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        this.onError('This browser cannot use the microphone here. Open in Safari or Chrome over HTTPS, or type instead.'); return;
      }
      try {
        await this.unlock();
        const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if (ticket !== this.captureId) {stream.getTracks().forEach(t=>t.stop()); return;}
        this.stream = stream;
        const source = this.context.createMediaStreamSource(stream);
        this.meter = this.context.createAnalyser(); this.meter.fftSize = 1024; source.connect(this.meter);
        // Preserve browser echo cancellation/AGC. Avoid aggressive gain that amplifies room echo.
        this.source = source;
        const mime = ['audio/webm;codecs=opus','audio/mp4','audio/webm','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
        if (!mime) throw new Error('Unsupported microphone format');
        const recorder = new MediaRecorder(stream,{mimeType:mime,audioBitsPerSecond:64000});
        this.recorder = recorder; const chunks=[]; let bytes=0;
        recorder.ondataavailable = e => {if(e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>1800000)this.stopCapture(false);}};
        recorder.onerror = () => {this.stopCapture(true);this.onError('Microphone interrupted. Tap Speak again, or type.');};
        recorder.onstop = () => {
          source.disconnect(); stream.getTracks().forEach(t=>t.stop());
          if (ticket === this.captureId && this.hasSpeech && bytes > 200) this.onAudio(new Blob(chunks,{type:mime.split(';')[0]}));
          else if (ticket === this.captureId) this.onState('READY','We did not catch speech. Tap the microphone to try again.');
        };
        this.recording=true; this.hasSpeech=false; this.started=performance.now(); this.lastVoice=this.started; this.voiced=0;
        recorder.start(200); this.onState('LISTENING','Speak naturally. A pause sends your message.');
        this.timer=setInterval(()=>{
          if (!this.recording) return;
          const data=new Float32Array(this.meter.fftSize);this.meter.getFloatTimeDomainData(data);
          const rms=Math.sqrt(data.reduce((s,n)=>s+n*n,0)/data.length);
          this.onLevel(Math.min(1,rms*18));
          const now=performance.now();
          if(rms>=0.006){this.lastVoice=now;this.voiced+=60;if(this.voiced>=240)this.hasSpeech=true;}
          if ((this.hasSpeech&&now-this.lastVoice>1450)||(now-this.started>45000)||(!this.hasSpeech&&now-this.started>12000)) this.stopCapture(false);
        },60);
      } catch (e) {
        if(ticket!==this.captureId)return;
        this.stopCapture(true);
        this.onError(e.name==='NotAllowedError'?'Microphone permission is off. Enable it in your browser, or type your message.':'The microphone could not start. Check your device, or type instead.');
      }
    }
    stopCapture(cancel=true) {
      if(cancel)++this.captureId;
      clearInterval(this.timer);this.recording=false;
      if(this.recorder&&this.recorder.state!=='inactive')this.recorder.stop();
      this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;this.onLevel(0);
    }
    stopPlayback() {
      ++this.playId;this.audio.pause();this.audio.onended=null;this.audio.onerror=null;
      cancelAnimationFrame(this.frame);if(this.objectURL)URL.revokeObjectURL(this.objectURL);
      this.objectURL=null;this.audio.removeAttribute('src');this.audio.load();this.onLevel(0);
      if(this.finishPlayback){this.finishPlayback(false);this.finishPlayback=null;}
    }
    async play(response) {
      this.stopCapture(true);this.stopPlayback();const ticket=this.playId;
      await this.unlock();
      // Fetch is streamed from the server; a bounded Blob works on iPad Safari as well as desktop.
      const blob=await response.blob();
      if(ticket!==this.playId)return false;
      if(!blob.size)throw new Error('No spoken audio received');
      this.objectURL=URL.createObjectURL(blob);this.audio.src=this.objectURL;
      return new Promise(resolve=>{
        this.finishPlayback=resolve;
        this.audio.onended=()=>{if(ticket!==this.playId)return;this.onLevel(0);cancelAnimationFrame(this.frame);this.finishPlayback=null;resolve(true);};
        this.audio.onerror=()=>{this.finishPlayback=null;resolve(false);};
        this.audio.play().then(()=>{
          if(ticket!==this.playId)return;
          this.onState('SPEAKING','Axel is speaking · microphone paused');
          const animate=()=>{if(ticket!==this.playId||this.audio.paused)return;const bins=new Uint8Array(this.speakerMeter.frequencyBinCount);this.speakerMeter.getByteFrequencyData(bins);this.onLevel(Math.min(1,bins.reduce((a,b)=>a+b,0)/bins.length/70));this.frame=requestAnimationFrame(animate);};animate();
        }).catch(()=>{this.finishPlayback=null;resolve(false);});
      });
    }
    stop() {this.stopCapture(true);this.stopPlayback();}
  }
  root.ExperienceVoice=ExperienceVoice;
})(typeof window==='undefined'?globalThis:window);
