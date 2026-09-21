import {validPage, followupDraft, isUserCaption} from './concierge-actions.js';
const config = JSON.parse(document.getElementById('conciergeConfig').textContent);
const employeeName = config.employeeName || 'Guru';
const $ = id => document.getElementById(id);
const frame = $('guideFrame'), panel = document.querySelector('.guide-companion');
const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
const directory = config.pages;
let page = config.initialPage, history = [page], dirty = false, focusAfterLoad = null, pageLoading = false;
let call = null, connection = null, busy = false, generation = 0, timer = null, replyTimer = null;
let callStarted = 0, typed = [], captions = [], formTouched = false, submissionId = crypto.randomUUID();
let captionOrder = new Map(), captionSequence = 0, deliveryPending = false, typedCaptionIds = new Set();
let pendingStart = null, connectingTimer = null, preparedAudioContext = null;
let preparedMicStream = null;
let typingTimer = null, typingCuePending = false, lastTypingCue = 0, typingBuffer = null;
let gestureTimer = null;
let contextQueue = Promise.resolve(), transferPending = false, preparedHandoff = null;
function saveContext(details) {
  const current=call, run=generation;
  const work=()=>{if(!current?.contextUrl || current!==call || run!==generation)throw new Error('Reconnect with Guru to make this introduction.');return post(current.contextUrl,details);};
  const result=contextQueue.then(work,work);contextQueue=result.catch(()=>{});return result;
}
async function introduceEmployee(args) {
  if(transferPending)return;
  if(!call?.contextUrl || !connection){showPage('demo',{fromAgent:true,search:'?industry='+encodeURIComponent(args.industry)});return;}
  transferPending=true;
  const active=connection, run=generation;
  try {
    const saved=await saveContext({...args,mode:active.micEnabled?'voice':'text'});
    const canContinue=()=>connection===active && generation===run && !$('guideText').value.trim() && !deliveryPending;
    if(!canContinue())return;
    status('Guru is finishing your introduction…');
    const finished=await active.waitForSpeechEnd({shouldContinue:canContinue});
    if(!canContinue())return;
    if(!finished){status('The introduction paused while Guru was still speaking. Ask Guru to introduce you again when you’re ready.');return;}
    preparedHandoff={id:saved.handoff,industry:saved.industry};
    showPage('demo',{fromAgent:true,search:'?industry='+encodeURIComponent(saved.industry)+'&handoff='+encodeURIComponent(saved.handoff),hash:'#employeePanel'});
  } catch(error) {status('The introduction could not be prepared. Please ask Guru to try again.',true);}
  finally {transferPending=false;}
}
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false;
function gesture(kind='navigate') {
  if(config.industry || reducedMotion())return;
  const stage=$('guideStage'), clip=$('guideGestureVideo');
  clearTimeout(gestureTimer);stage.dataset.gesture=kind;stage.classList.add('gesturing');
  if(clip){clip.currentTime=0;clip.play().catch(()=>stage.classList.remove('gesturing'));}
  gestureTimer=setTimeout(()=>{stage.classList.remove('gesturing');clip?.pause();},4800);
}
function speechLevel(level){$('guideStage').style?.setProperty('--speech',String(Math.max(0,Math.min(1,level))));}
async function notifyTyping(){
  const active=connection;
  if(!active || active.micEnabled || !config.typingAudioUrl || typingCuePending || deliveryPending || !$('guideText').value.trim() || Date.now()-lastTypingCue<30000)return;
  typingCuePending=true;
  try{
    if(!typingBuffer){const response=await fetch(config.typingAudioUrl);if(!response.ok)throw new Error('Typing cue unavailable');typingBuffer=await response.arrayBuffer();}
    const sent=await active.sendAudio(typingBuffer,{control:true,shouldSend:()=>connection===active && !active.micEnabled && !deliveryPending && !!$('guideText').value.trim()});
    if(sent && connection===active){lastTypingCue=Date.now();status('Take your time typing. Guru has been notified to wait. Your draft is sent only when you press Send.');}
  }catch(_){/* Typing never blocks the actual message. */}finally{typingCuePending=false;}
}
$('guideText').addEventListener('input',()=>{
  clearTimeout(replyTimer);clearTimeout(typingTimer);
  if(connection && $('guideText').value.trim())typingTimer=setTimeout(notifyTyping,1000);
});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const tellHost = type => { if(config.embedded && parent!==window)parent.postMessage({source:config.industry?'aibg-demo-employee':'aibg-hero-concierge',type},location.origin); };
function connectionProgress(step) { $('guideConnectingStep').textContent=step.replaceAll('Guru',employeeName); }
function beginConnectionProgress() {
  const started=Date.now();$('guideConnecting').hidden=false;
  const tick=()=>{$('guideConnectingTime').textContent=`${Math.floor((Date.now()-started)/1000)}s`;if(Date.now()-started>20000 && busy)status('Guru is taking a little longer to join. You can keep browsing or request a team follow-up.');};
  tick();connectingTimer=setInterval(tick,1000);
}
function stopConnectionProgress(){clearInterval(connectingTimer);connectingTimer=null;$('guideConnecting').hidden=true;}
function status(text, isError=false) { $('guideStatus').textContent=text.replaceAll('Guru',employeeName); $('guideStatus').classList.toggle('error',isError); }
async function post(url, data={}) {
  const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),30000);
  try {
    const response = await fetch(url, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(data),signal:controller.signal});
    let result;
    try { result=await response.json(); } catch (_) { throw new Error('The connection was interrupted. Please try again.'); }
    if (!response.ok) { const error=new Error(result.error || 'This request could not complete. Please try again.');error.existingCall=result.existingCall;throw error; }
    return result;
  } catch(error) {if(error.name==='AbortError')throw new Error('The connection took too long. Please try again.');throw error;}
  finally {clearTimeout(timeout);}
}
function showPage(key, {back=false, fromAgent=false, search='', hash=''}={}) {
  if (!validPage(directory,key)) return;
  const item=directory[key];
  if (!item.embedded) { $('guidePortal').hidden=false; panel.classList.remove('minimized'); syncMinimize(); $('guidePortal').scrollIntoView({block:'nearest'}); return; }
  const welcome=document.body.classList.contains('guide-welcome');
  if (key===page && !search && !hash && !welcome) return;
  if (dirty && !confirm('Leave this page? Your unfinished form may be lost.')) return;
  document.body.classList.remove('guide-welcome');
  tellHost('browse');
  if(fromAgent)gesture('navigate');
  dirty=false; page=key;pageLoading=true;focusAfterLoad=null;
  if (!back) history.push(key);
  const url=new URL(item.path,location.origin);
  if(typeof search==='string' && search.length<2000)url.search=search;
  if(typeof hash==='string' && hash.length<200)url.hash=hash;
  url.searchParams.set('guided','1');
  frame.src=url.href;
  $('guidePageLabel').textContent=item.label;
  $('guidePageStatus').textContent=fromAgent?`Guru is showing you ${item.label.toLowerCase()}.`:`Opening ${item.label.toLowerCase()}…`;
  $('guideBack').disabled=history.length<2;
  document.querySelectorAll('[data-page]').forEach(button=>button.setAttribute('aria-current',button.dataset.page===key?'page':'false'));
  if (innerWidth<761) { panel.classList.add('minimized'); syncMinimize(); }
}
function focusSection(section) {
  if (!['top','content','calendar','assessment-request'].includes(section)) return;
  if(document.body.classList.contains('guide-welcome') && !['calendar','assessment-request'].includes(section))showPage(page,{fromAgent:true});
  if (['calendar','assessment-request'].includes(section) && page!=='assessment') { showPage('assessment',{fromAgent:true}); if(page==='assessment')focusAfterLoad=section; return; }
  if(pageLoading){focusAfterLoad=section;return;}
  gesture(section==='top'?'up':'down');
  frame.contentWindow.postMessage({source:'aibg-concierge',type:'focus',section},location.origin);
}
function openFollowup(args={}) {
  const dialog=$('guideFollowupDialog'), form=$('guideFollowupForm');
  // Existing user edits take precedence over a later model tool call.
  if (!formTouched) {
    for(const [name,value] of Object.entries(followupDraft(args))) form.elements[name].value=value;
  }
  if (!dialog.open) dialog.showModal();
}
function tool(event) {
  if (!event || !event.args || typeof event.args!=='object' || Array.isArray(event.args)) return;
  if(config.industry)return;
  if(event.tool==='remember_visitor'){saveContext(event.args).catch(()=>status('Your name or request could not be remembered. Please ask Guru to try again.',true));return;}
  if ($('guideText').value.trim() || deliveryPending) return;
  if (event.tool==='introduce_demo_employee' && Object.hasOwn(config.demoDirectory || {},event.args.industry)) {
    introduceEmployee(event.args);
  } else if(event.tool==='scroll_page' && ['up','down'].includes(event.args.direction)){
    gesture(event.args.direction);frame.contentWindow.postMessage({source:'aibg-concierge',type:'scroll',direction:event.args.direction},location.origin);
  } else if (event.tool==='navigate_page') showPage(event.args.page,{fromAgent:true});
  else if(event.tool==='focus_section') focusSection(event.args.section);
  else if(event.tool==='prepare_followup') openFollowup(event.args);
}
function syncMinimize() {
  const small=panel.classList.contains('minimized');
  $('guideMinimize').textContent=small?'+':'−';
  $('guideMinimize').setAttribute('aria-label',small?'Expand video assistant':'Minimize video assistant');
  $('guideMinimize').setAttribute('aria-expanded',String(!small));
  $('guideExpand').textContent=small?'Show assistant':'Focus page';
  $('guideExpand').setAttribute('aria-expanded',String(small));
}
$('guideMinimize').addEventListener('click',()=>{panel.classList.toggle('minimized');syncMinimize();});
$('guideExpand').addEventListener('click',()=>{panel.classList.toggle('minimized');syncMinimize();$('guideExpand').setAttribute('aria-expanded',String(panel.classList.contains('minimized')));});
$('guideBack').addEventListener('click',()=>{if(history.length>1){const target=history[history.length-2];showPage(target,{back:true});if(page===target)history.pop();$('guideBack').disabled=history.length<2;}});
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>showPage(button.dataset.page)));
$('guideFollowupOpen').addEventListener('click',()=>openFollowup());
$('guideFollowupClose').addEventListener('click',()=>$('guideFollowupDialog').close());
document.querySelectorAll('[data-guide-terms]').forEach(link=>link.addEventListener('click',event=>{
  if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  event.preventDefault();
  $('guideTermsDialog').showModal();$('guideTermsTitle').focus();
}));
document.querySelectorAll('[data-close-terms]').forEach(button=>button.addEventListener('click',()=>$('guideTermsDialog').close()));
window.addEventListener('message',async event=>{
  if(event.origin===location.origin && event.source===parent && config.industry && event.data?.source==='aibg-demo-host' && event.data.type==='close') {
    if(pendingStart){try{await pendingStart;}catch(_){}}
    const closed=await endCall();
    if(closed)tellHost('closed');
    return;
  }
  if(event.origin!==location.origin || event.source!==frame.contentWindow || event.data?.source!=='aibg-guided-page')return;
  if(event.data.type==='demo-handoff' && !config.industry && Object.hasOwn(config.demoDirectory || {},event.data.industry)) {
    if(event.data.handoff && (preparedHandoff?.id!==event.data.handoff || preparedHandoff?.industry!==event.data.industry))return;
    if(pendingStart){try{await pendingStart;}catch(_){}}
    if(connection?.waitForSpeechEnd && !await connection.waitForSpeechEnd({settleMs:event.data.handoff && event.data.handoff===preparedHandoff?.id?0:1600})) {
      frame.contentWindow.postMessage({source:'aibg-concierge',type:'demo-handoff-ready',ok:false},location.origin);return;
    }
    const closed=await endCall(event.data.handoff?'Your demo employee is joining. I’ll be here if you need me.':'I’ve introduced you to your demo employee. Choose Start conversation in their window when you’re ready.');
    if(closed){panel.classList.add('minimized');syncMinimize();}
    frame.contentWindow.postMessage({source:'aibg-concierge',type:'demo-handoff-ready',ok:closed},location.origin);
  }
  if(event.data.type==='dirty')dirty=event.data.dirty===true;
  if(event.data.type==='navigate') {
    const key=Object.keys(directory).find(key=>directory[key].path===event.data.path);
    if(key)showPage(key,{search:event.data.search,hash:event.data.hash});
  }
  if(event.data.type==='loaded' && event.data.path===directory[page].path) {
    pageLoading=false;
    $('guidePageStatus').textContent='';
    if(focusAfterLoad){focusSection(focusAfterLoad);focusAfterLoad=null;}
  }
});
function controls(active) {
  $('guideStart').hidden=busy||active; $('guideStart').disabled=!config.available;
  $('guideEnd').hidden=!busy&&!active; $('guideMic').hidden=!active;
  $('guideInputMode').hidden=busy||active; $('guideConsent').hidden=busy||active||!config.available;
  $('guideTextForm').hidden=!active;panel.classList.toggle('in-call',active);
  $('guideListening').hidden=!active;
  $('guideInterrupt').hidden=true;
  $('guideMicBoost').hidden=true;
  $('guideSound').hidden=!active; $('guideTimer').hidden=!active;
  if(!active)$('guideStage').classList.remove('live');
}
function renderTranscript(entries=captions) {
  captions=entries;
  const normalize=value=>value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu,'');
  for(const entry of entries)if(!captionOrder.has(entry.id) && isUserCaption(entry) && !connection?.micEnabled)typedCaptionIds.add(entry.id);
  const merged=[...typed,...entries.filter(entry=>!typedCaptionIds.has(entry.id) && !(isUserCaption(entry)&&typed.some(item=>normalize(item.text)===normalize(entry.text))))];
  for(const entry of merged)if(!captionOrder.has(entry.id))captionOrder.set(entry.id,captionSequence++);
  merged.sort((a,b)=>captionOrder.get(a.id)-captionOrder.get(b.id));
  const region=$('guideTranscript');region.replaceChildren();
  for(const entry of merged.slice(-40)) {
    if(!entry.text)continue;
    const p=document.createElement('p'),user=isUserCaption(entry);
    p.dataset.role=user?'user':'assistant';p.textContent=(user?'You: ':employeeName+': ')+entry.text;
    region.appendChild(p);
  }
  region.scrollTop=region.scrollHeight;
  if(entries.length && !isUserCaption(entries[entries.length-1]) && !deliveryPending){
    clearTimeout(replyTimer);replyTimer=null;
    if(connection)status('You’re connected. Type below or use your mic.');
  }
}
async function cancelProvider(record) {
  if(!record)return true;
  try { await post(record.stopUrl); return true; } catch (_) {
    try {await wait(700);await post(record.stopUrl);return true;} catch (_) { return false; }
  }
}
async function endCall(message='Call ended. You can keep exploring or book your growth consultation.') {
  ++generation;busy=false;clearInterval(timer);clearTimeout(replyTimer);clearTimeout(typingTimer);stopConnectionProgress();speechLevel(0);
  deliveryPending=false;$('guideTextSend').disabled=false;$('guideMic').disabled=false;
  const oldConnection=connection,oldCall=call;connection=null;call=null;
  preparedMicStream?.getTracks().forEach(track=>track.stop());preparedMicStream=null;
  if(!oldConnection && preparedAudioContext){await preparedAudioContext.close().catch(()=>{});preparedAudioContext=null;}
  controls(false);$('guideState').textContent='Call ended';status(message);
  $('guideVideo').srcObject=null;$('guideAudio').srcObject=null;
  // Provider cancellation must still run if browser media cleanup fails.
  if(oldConnection){try{await oldConnection.end();}catch(_){}}
  const closed=await cancelProvider(oldCall);
  if(!closed){call=oldCall;$('guideEnd').hidden=false;status('The call has not closed yet. Please press End call to retry.',true);}
  return closed;
}
$('guideEnd').addEventListener('click',()=>endCall());
$('guideClose')?.addEventListener('click',async()=>{
  $('guideClose').disabled=true;
  // Keep the iframe alive until an in-flight creation can be cancelled.
  if(pendingStart){try{await pendingStart;}catch(_){}}
  if(await endCall())tellHost('close');
  else $('guideClose').disabled=false;
});
$('guideSound').addEventListener('click',async()=>{
  const audio=$('guideAudio');
  try {
    const enable=audio.paused||audio.muted;
    if(enable){if(connection)await connection.unlockAudio();else await audio.play();audio.muted=false;}
    else audio.muted=true;
    $('guideSound').textContent=audio.muted?'Sound off':'Sound on';
    $('guideSound').setAttribute('aria-pressed',String(!audio.muted));
  }catch(_){status('Your browser could not play the audio. Try pressing Sound on again.',true);}
});
$('guideMic').addEventListener('click',async()=>{
  if(!connection)return;
  $('guideMic').disabled=true;$('guideTextSend').disabled=true;
  try {await connection.setMic(!connection.micEnabled);syncMic();}
  catch(_){status('Microphone access is unavailable. You can keep typing below.',true);}
  finally{$('guideMic').disabled=false;$('guideTextSend').disabled=false;}
});
function syncMic(state=connection?.listeningState){
  const enabled=connection?.micEnabled||false;
  const labels={listening:'Your turn · listening', 'assistant-speaking':employeeName+' is speaking · mic paused', waiting:'Waiting for '+employeeName+' · mic paused', sending:'Sending your typed message · mic paused', reconnecting:'Reconnecting · mic paused', 'audio-paused':'Tap Hear '+employeeName+' to resume audio'};
  $('guideListeningLabel').textContent=enabled?(labels[state]||'Your turn · listening'):'Typing mode · microphone off';
  $('guideListening').dataset.state=enabled?state||'listening':'muted';
  $('guideMic').textContent=enabled?'Mute mic':'Turn mic on';$('guideMic').setAttribute('aria-pressed',String(enabled));
  $('guideInterrupt').hidden=!enabled || !['assistant-speaking','waiting'].includes(state) || deliveryPending;
  $('guideMicBoost').hidden=!enabled;
  $('guideMicBoost').setAttribute('aria-pressed',String(connection?.micBoosted||false));
  $('guideMicBoost').textContent=connection?.micBoosted?'Quiet voice boost on':'Quiet voice boost';
}
$('guideMicBoost').addEventListener('click',()=>{
  if(!connection)return;
  connection.setMicBoost(!connection.micBoosted);syncMic();
});
$('guideInterrupt').addEventListener('click',async()=>{
  const active=connection;if(!active || deliveryPending)return;
  $('guideInterrupt').disabled=true;
  try {if(await active.interrupt() && connection===active){syncMic();status('Go ahead—your microphone is open.');}}
  catch(_){if(connection===active)status('Tap Sound on to resume audio, then try again.',true);}
  finally{$('guideInterrupt').disabled=false;}
});
async function startConversation({handoff=!!config.handoff?.autoStart}={}){
  if(busy||connection||!config.available)return;
  const transfer=handoff && config.handoff?.autoStart ? config.handoff : null;
  if(!transfer && !$('guideConsentCheck').checked){status('Please agree to the AI Business Gurus Terms of Service before starting.',true);$('guideConsentCheck').focus();return;}
  if(window.AudioContext){preparedAudioContext=new AudioContext();preparedAudioContext.resume().catch(()=>{});}
  lastTypingCue=0;
  const run=++generation;busy=true;controls(false);$('guideState').textContent='Connecting';status('Connecting you to Guru…');
  beginConnectionProgress();connectionProgress('Preparing your conversation');
  typed=[];captions=[];typedCaptionIds.clear();captionOrder.clear();captionSequence=0;renderTranscript([]);
  let record=null;
  try {
    let mode=transfer?.mode || document.querySelector('[name=inputMode]:checked').value;
    const {connectCall,microphoneConstraints}=await import(config.callModuleUrl);
    if(run!==generation)return;
    if(mode==='voice') {
      try {
        if(!navigator.mediaDevices?.getUserMedia)throw new Error('Your browser cannot access a microphone here. Choose Type to continue.');
        const permission=await navigator.mediaDevices.getUserMedia(microphoneConstraints);
        if(run!==generation){permission.getTracks().forEach(track=>track.stop());return;}
        preparedMicStream=permission;
      } catch(error) {if(!transfer)throw error;mode='text';}
    }
    if(run!==generation)return;
    pendingStart=post(config.startUrl,{consent:!transfer && $('guideConsentCheck').checked,page,industry:config.industry || '',...(transfer?{handoff:transfer.id}:{})});
    try{record=await pendingStart;}finally{pendingStart=null;}
    if(transfer)config.handoff.autoStart=false;
    if(run!==generation){await cancelProvider(record);return;}call=record;
    let credentials=null;
    connectionProgress('Bringing Guru online');
    const deadline=Date.now()+90000;
    for(let attempt=0;attempt<65 && Date.now()<deadline;attempt++){
      if(run!==generation)return;
      const ready=await post(record.pollUrl);
      if(run!==generation)return;
      if(ready.status==='ready'){credentials=ready.credentials;break;}
      await wait(attempt<10?700:1500);
    }
    if(!credentials)throw new Error('Guru took too long to connect. Please try again.');
    if(run!==generation)return;
    connectionProgress('Connecting video and sound');
    const live=await connectCall({credentials,audioContext:preparedAudioContext,microphoneStream:preparedMicStream,video:$('guideVideo'),audio:$('guideAudio'),
      onSpeechLevel:level=>{if(run===generation)speechLevel(level);},
      onInputLevel:level=>{if(run===generation)$('guideListening').style?.setProperty('--input-level',String(level));},
      onListeningState:state=>{if(run===generation)syncMic(state);},
      onTranscript:entries=>{if(run===generation)renderTranscript(entries);},
      onTool:event=>{if(run===generation)tool(event);},
      onState:state=>{if(run!==generation)return;if(state==='ended')endCall();else if(state==='reconnecting')status('Reconnecting… your conversation will resume shortly.');else if(state==='active')status('Connected. Type below or use your mic.');else if(state==='mic-lost'){syncMic();status('Microphone access stopped. Turn your mic on again or keep typing.',true);}else if(state==='audio-paused')status('Audio paused by your browser. Tap Sound on to resume.',true);},
      onMediaReady:()=>{if(run===generation)$('guideStage').classList.add('live');},
      onAudioBlocked:()=>{if(run===generation){status('Tap Hear Guru to enable sound.');$('guideSound').textContent='Hear '+employeeName;}},
    });
    if(run!==generation){await live.end();await cancelProvider(record);return;}
    connection=live;preparedAudioContext=null;preparedMicStream=null;busy=false;stopConnectionProgress();callStarted=Date.now();controls(true);$('guideState').textContent='Live AI';
    syncMic();status(connection.audioBlocked?`Tap Hear ${employeeName} to enable sound, then type or turn on your mic.`:'You’re connected. Type below or turn on your mic.');
    document.querySelector('.guide-transcript').open=true;
    const tick=()=>{
      const left=Math.max(0,config.maxSeconds-Math.floor((Date.now()-callStarted)/1000));
      $('guideTimer').textContent=`${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`;
      if(left===30)status('About 30 seconds left. You can book a consultation or request a follow-up anytime.');
      if(left===0)endCall('This call has finished. Book a consultation or send a follow-up to keep things moving.');
    };
    tick();timer=setInterval(tick,1000);$('guideText').focus();
  } catch(error) {
    if(run!==generation)return;
    if(error.existingCall){await endCall(error.message);call=error.existingCall;$('guideEnd').hidden=false;$('guideState').textContent='Previous call';return;}
    await endCall(error.name==='NotAllowedError'?'Microphone permission was declined. Choose Type and start again.':error.message||'The video connection could not start. Please try again.');
    $('guideState').textContent='Try again';$('guideStatus').classList.add('error');
  }
}
$('guideStart').addEventListener('click',()=>startConversation());
$('guideTextForm').addEventListener('submit',async event=>{
  event.preventDefault();const text=$('guideText').value.trim();if(!text||!connection||deliveryPending)return;
  clearTimeout(typingTimer);
  const active=connection,typedEntry={id:crypto.randomUUID(),text,local:true};$('guideTextSend').disabled=true;$('guideMic').disabled=true;deliveryPending=true;
  try {
    await active.unlockAudio();
    status('Delivering your message to Guru…');
    const currentCall=call;
    const task=await post(currentCall.textUrl,{message:text});
    let audio=null;
    for(let attempt=0;attempt<35;attempt++) {
      if(connection!==active)return;
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),20000);
      try{
        const response=await fetch(task.pollUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({token:task.token}),signal:controller.signal});
        if(response.ok && response.headers.get('Content-Type')?.startsWith('audio/')){audio=await response.arrayBuffer();break;}
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'Message delivery failed.');
      }finally{clearTimeout(timeout);}
      await wait(1000);
    }
    if(!audio)throw new Error('Message delivery timed out.');
    if(connection!==active)return;
    $('guideMic').disabled=true;
    if(!await active.sendAudio(audio))throw new Error('Message delivery was interrupted.');
    lastTypingCue=0;
    if(connection!==active)return;
    typed.push(typedEntry);typed=typed.slice(-20);renderTranscript();
    if($('guideText').value.trim()===text)$('guideText').value='';
    else typingTimer=setTimeout(notifyTyping,1000);
    status('Message sent. Guru is responding…');
    replyTimer=setTimeout(()=>{if(connection===active && !$('guideText').value.trim())status('Still waiting for a reply. You can try your microphone or end this call and reconnect.',true);},45000);
  } catch(_){if(connection===active)status('Your message could not be sent. Please try again.',true);}
  finally{if(connection===active){deliveryPending=false;$('guideTextSend').disabled=false;$('guideMic').disabled=false;syncMic();$('guideText').focus();}}
});
$('guideFollowupForm').addEventListener('input',()=>{formTouched=true;});
$('guideFollowupForm').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;if(!form.reportValidity())return;
  $('guideSubmit').disabled=true;$('guideFormStatus').textContent='Sending your request…';
  form.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
  const data=new FormData(form);data.set('submission_id',submissionId);
  try {
    const response=await fetch(config.followupUrl,{method:'POST',headers:{'X-CSRFToken':csrf},body:data,credentials:'same-origin'});
    const result=await response.json();
    if(!response.ok){for(const name of Object.keys(result.fields||{}))form.elements[name]?.setAttribute('aria-invalid','true');throw new Error(result.error||'Your request could not be sent.');}
    $('guideFormStatus').textContent=`Request received. Reference #${result.reference}. Our team will follow up. A calendar time has not been reserved.`;
    $('guideSubmit').textContent='Request sent';
  }catch(error){$('guideFormStatus').textContent=error.message||'Please try again.';$('guideSubmit').disabled=false;}
});
window.addEventListener('pagehide',()=>{
  preparedMicStream?.getTracks().forEach(track=>track.stop());
  connection?.end();
  if(call)fetch(call.stopUrl,{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/json'},body:'{}',credentials:'same-origin',keepalive:true}).catch(()=>{});
});
tellHost('ready');
if(config.industry && parent!==window && window.ResizeObserver){
  const resize=new ResizeObserver(()=>{
    const height=Math.ceil(panel.offsetHeight+(document.querySelector('.guide-embed-bar')?.offsetHeight || 0));
    parent.postMessage({source:'aibg-demo-employee',type:'resize',height},location.origin);
  });
  resize.observe(panel);
}
if(config.handoff?.autoStart)startConversation({handoff:true});
