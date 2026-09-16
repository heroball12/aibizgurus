import {validPage, followupDraft, isUserCaption} from './concierge-actions.js';
const config = JSON.parse(document.getElementById('conciergeConfig').textContent);
const $ = id => document.getElementById(id);
const frame = $('guideFrame'), panel = document.querySelector('.guide-companion');
const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
const directory = config.pages;
let page = config.initialPage, history = [page], dirty = false, focusAfterLoad = null, pageLoading = false;
let call = null, connection = null, busy = false, generation = 0, timer = null, replyTimer = null;
let callStarted = 0, typed = [], captions = [], formTouched = false, submissionId = crypto.randomUUID();
let captionOrder = new Map(), captionSequence = 0, deliveryPending = false, typedCaptionIds = new Set();
let pendingStart = null, connectingTimer = null;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const tellHost = type => { if(config.embedded && parent!==window)parent.postMessage({source:'aibg-hero-concierge',type},location.origin); };
function connectionProgress(step) { $('guideConnectingStep').textContent=step; }
function beginConnectionProgress() {
  const started=Date.now();$('guideConnecting').hidden=false;
  const tick=()=>{$('guideConnectingTime').textContent=`${Math.floor((Date.now()-started)/1000)}s`;if(Date.now()-started>20000 && busy)status('Guru is taking a little longer to join. You can keep browsing or request a team follow-up.');};
  tick();connectingTimer=setInterval(tick,1000);
}
function stopConnectionProgress(){clearInterval(connectingTimer);connectingTimer=null;$('guideConnecting').hidden=true;}
function status(text, isError=false) { $('guideStatus').textContent=text; $('guideStatus').classList.toggle('error',isError); }
async function post(url, data={}) {
  const response = await fetch(url, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(data)});
  let result;
  try { result=await response.json(); } catch (_) { throw new Error('The connection was interrupted. Please try again.'); }
  if (!response.ok) { const error=new Error(result.error || 'This request could not complete. Please try again.');error.existingCall=result.existingCall;throw error; }
  return result;
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
  if (event.tool==='navigate_page') showPage(event.args.page,{fromAgent:true});
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
window.addEventListener('message',event=>{
  if(event.origin!==location.origin || event.source!==frame.contentWindow || event.data?.source!=='aibg-guided-page')return;
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
    p.dataset.role=user?'user':'assistant';p.textContent=(user?'You: ':'Guru: ')+entry.text;
    region.appendChild(p);
  }
  region.scrollTop=region.scrollHeight;
  if(entries.length && !isUserCaption(entries[entries.length-1]) && !deliveryPending){
    clearTimeout(replyTimer);replyTimer=null;
    if(connection)status('You’re connected. Type below or use your mic.');
  }
}
async function cancelProvider(record) {
  if(!record)return;
  try { await post(record.stopUrl); } catch (_) {
    try {await wait(700);await post(record.stopUrl);} catch (_) { /* Provider has a hard maximum session duration. */ }
  }
}
async function endCall(message='Call ended. You can keep exploring or book your growth consultation.') {
  ++generation;busy=false;clearInterval(timer);clearTimeout(replyTimer);stopConnectionProgress();
  const oldConnection=connection,oldCall=call;connection=null;call=null;
  controls(false);$('guideState').textContent='Call ended';status(message);
  $('guideVideo').srcObject=null;$('guideAudio').srcObject=null;
  if(oldConnection)await oldConnection.end();
  await cancelProvider(oldCall);
}
$('guideEnd').addEventListener('click',()=>endCall());
$('guideClose')?.addEventListener('click',async()=>{
  $('guideClose').disabled=true;
  // Keep the iframe alive until an in-flight creation can be cancelled.
  if(pendingStart){try{await pendingStart;}catch(_){}}
  await endCall();tellHost('close');
});
$('guideSound').addEventListener('click',async()=>{
  const audio=$('guideAudio');
  try {
    if(audio.paused){audio.muted=false;await audio.play();}else audio.muted=!audio.muted;
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
function syncMic(){const enabled=connection?.micEnabled||false;$('guideMic').textContent=enabled?'Mute mic':'Turn mic on';$('guideMic').setAttribute('aria-pressed',String(enabled));}
$('guideStart').addEventListener('click',async()=>{
  if(busy||connection||!config.available)return;
  if(!$('guideConsentCheck').checked){status('Please agree to the AI Business Gurus Terms of Service before starting.',true);$('guideConsentCheck').focus();return;}
  const run=++generation;busy=true;controls(false);$('guideState').textContent='Connecting';status('Connecting you to Guru…');
  beginConnectionProgress();connectionProgress('Preparing your conversation');
  typed=[];captions=[];typedCaptionIds.clear();captionOrder.clear();captionSequence=0;renderTranscript([]);
  let record=null;
  try {
    const mode=document.querySelector('[name=inputMode]:checked').value;
    const modulePromise=import(config.callModuleUrl);
    if(mode==='voice') {
      if(!navigator.mediaDevices?.getUserMedia)throw new Error('Your browser cannot access a microphone here. Choose Type to continue.');
      const permission=await navigator.mediaDevices.getUserMedia({audio:true,video:false});permission.getTracks().forEach(track=>track.stop());
    }
    if(run!==generation)return;
    pendingStart=post(config.startUrl,{consent:true,page});
    try{record=await pendingStart;}finally{pendingStart=null;}
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
    const {connectCall}=await modulePromise;
    if(run!==generation)return;
    connectionProgress('Connecting video and sound');
    const live=await connectCall({credentials,video:$('guideVideo'),audio:$('guideAudio'),
      onTranscript:entries=>{if(run===generation)renderTranscript(entries);},
      onTool:event=>{if(run===generation)tool(event);},
      onState:state=>{if(run!==generation)return;if(state==='ended')endCall();else if(state==='reconnecting')status('Reconnecting… your conversation will resume shortly.');},
      onVideo:()=>{if(run===generation)$('guideStage').classList.add('live');},
      onAudioBlocked:()=>{status('Tap Hear Guru to enable sound.');$('guideSound').textContent='Hear Guru';},
    });
    if(run!==generation){await live.end();await cancelProvider(record);return;}
    connection=live;busy=false;stopConnectionProgress();callStarted=Date.now();controls(true);$('guideState').textContent='Live AI';
    if(mode==='voice') {try{await connection.setMic(true);}catch(_){status('Microphone unavailable. You can type below.',true);}}
    syncMic();status('You’re connected. Type below or turn on your mic.');
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
    if(error.existingCall){busy=false;stopConnectionProgress();call=error.existingCall;controls(false);$('guideEnd').hidden=false;$('guideState').textContent='Previous call';status(error.message,true);return;}
    await endCall(error.name==='NotAllowedError'?'Microphone permission was declined. Choose Type and start again.':error.message||'The video connection could not start. Please try again.');
    $('guideState').textContent='Try again';$('guideStatus').classList.add('error');
  }
});
$('guideTextForm').addEventListener('submit',async event=>{
  event.preventDefault();const text=$('guideText').value.trim();if(!text||!connection)return;
  const active=connection,typedEntry={id:crypto.randomUUID(),text,local:true};$('guideTextSend').disabled=true;$('guideMic').disabled=true;deliveryPending=true;
  try {
    await active.unlockAudio();
    status('Delivering your message to Guru…');
    const currentCall=call;
    const task=await post(currentCall.textUrl,{message:text});
    let audio=null;
    for(let attempt=0;attempt<35;attempt++) {
      if(connection!==active)return;
      const response=await fetch(task.pollUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({token:task.token})});
      if(response.ok && response.headers.get('Content-Type')?.startsWith('audio/')){audio=await response.arrayBuffer();break;}
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||'Message delivery failed.');
      await wait(1000);
    }
    if(!audio)throw new Error('Message delivery timed out.');
    if(connection!==active)return;
    $('guideMic').disabled=true;
    typed.push(typedEntry);typed=typed.slice(-20);renderTranscript();
    await active.sendAudio(audio);
    if(connection!==active)return;
    $('guideText').value='';status('Message sent. Guru is responding…');
    replyTimer=setTimeout(()=>status('No reply yet. You can try your microphone or request a team follow-up.',true),20000);
  } catch(_){if(connection===active)status('Your message could not be sent. Please try again.',true);}
  finally{deliveryPending=false;$('guideTextSend').disabled=false;$('guideMic').disabled=false;syncMic();if(connection)$('guideText').focus();}
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
  connection?.end();
  if(call)fetch(call.stopUrl,{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/json'},body:'{}',credentials:'same-origin',keepalive:true}).catch(()=>{});
});
tellHost('ready');
