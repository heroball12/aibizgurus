(() => {
  const app=document.getElementById('teamChatApp');if(!app)return;
  const stream=document.getElementById('chatMessages'),connection=document.getElementById('chatConnection'),errorBox=document.getElementById('chatError');
  const composer=document.getElementById('chatComposer'),textarea=document.getElementById('id_body'),fileInput=document.getElementById('attachmentInput');
  const jump=document.getElementById('newMessagesButton'),older=document.getElementById('loadOlderMessages');
  let messages=new Map(),timer,inFlight=false,failures=0,initialized=false,readThrough=0,reading=false,sending=false,nonce=null,pendingForm=null,loadingOlder=false,oldestExhausted=false;
  const nearBottom=()=>stream.scrollHeight-stream.scrollTop-stream.clientHeight<95;
  const text=(tag,value,cls)=>{const e=document.createElement(tag);e.textContent=value??'';if(cls)e.className=cls;return e;};
  const showError=value=>{errorBox.textContent=value;errorBox.hidden=!value;};
  async function post(url,body){const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':app.dataset.csrf},body,signal:AbortSignal.timeout(25000)});let result;try{result=await response.json();}catch{throw new Error('Your session or connection needs attention. Your draft is still here.');}if(!response.ok){const e=new Error(result.error||'Could not complete that action. Try again.');e.definite=response.status>=400&&response.status<500;throw e;}return result;}
  const formData=values=>{const f=new FormData();Object.entries(values).forEach(([k,v])=>f.append(k,v));return f;};
  function reactionButton(id,emoji,count,mine){const b=text('button',`${emoji}${count?' '+count:''}`,mine?'chat-reaction mine':'chat-reaction');b.type='button';b.dataset.reaction=emoji;b.dataset.messageId=id;b.setAttribute('aria-label',`React ${emoji}${count?`, ${count} reactions`:''}`);return b;}
  function build(message){
    const article=text('article','','team-message'+(message.mine?' mine':''));article.dataset.messageId=message.id;
    article.append(text('span',(message.sender||'S').slice(0,1).toUpperCase(),'chat-avatar'));
    const content=text('div','','team-message-content'),meta=document.createElement('header');meta.append(text('strong',message.sender),text('time',message.created));content.append(meta);
    const bubble=text('div','','chat-bubble');bubble.append(text('p',message.body));
    for(const file of message.attachments||[]){const a=text('a','📎 '+file.name,'chat-attachment');a.href=file.url;a.append(text('small',file.size));bubble.append(a);}
    content.append(bubble);
    const reactions=text('div','','chat-reactions');for(const r of message.reactions||[])reactions.append(reactionButton(message.id,r.emoji,r.count,r.mine));
    const picker=document.createElement('details');picker.className='chat-reaction-picker';picker.append(text('summary','☺'));picker.querySelector('summary').setAttribute('aria-label','Add reaction');const options=document.createElement('div');['👍','❤️','😂','🎉','🔥','✅','👀','💜','🚀'].forEach(e=>options.append(reactionButton(message.id,e)));picker.append(options);reactions.append(picker);content.append(reactions);article.append(content);return article;
  }
  function merge(items,{prepend=false}={}){
    const bottom=nearBottom(),height=stream.scrollHeight,top=stream.scrollTop;let changed=false,newIncoming=false;
    items.forEach(m=>{const previous=messages.get(m.id);if(!previous||JSON.stringify(previous)!==JSON.stringify(m)){changed=true;if(!previous&&!m.mine)newIncoming=true;messages.set(m.id,m);}});
    if(!changed)return;
    const sorted=[...messages.values()].sort((a,b)=>a.id-b.id);
    // Replace changed message nodes only; preserve selection and open reaction controls elsewhere.
    if(!initialized){stream.replaceChildren();initialized=true;}
    sorted.forEach(m=>{const existing=stream.querySelector(`[data-message-id="${m.id}"]`),signature=JSON.stringify(m);if(existing?.dataset.signature===signature)return;const node=build(m);node.dataset.signature=signature;if(existing)existing.replaceWith(node);else{const next=[...stream.children].find(e=>Number(e.dataset.messageId)>m.id);stream.insertBefore(node,next||null);}});
    if(prepend)stream.scrollTop=top+(stream.scrollHeight-height);else if(bottom){stream.scrollTop=stream.scrollHeight;jump.hidden=true;}else if(newIncoming)jump.hidden=false;
    markRead();
  }
  async function markRead(){
    if(document.hidden||!document.hasFocus()||!nearBottom()||reading)return;
    const highest=Math.max(0,...messages.keys());if(!highest||highest<=readThrough)return;
    reading=true;try{await post(app.dataset.readUrl,formData({through:highest}));readThrough=highest;window.dispatchEvent(new Event('team-chat-read'));}catch{}finally{reading=false;}
  }
  function readers(data){const mine=[...messages.values()].filter(m=>m.mine).sort((a,b)=>b.id-a.id)[0];const names=mine?(data.readers||[]).filter(r=>Date.parse(r.at)>=Date.parse(mine.timestamp)).map(r=>r.name):[];document.getElementById('chatReadReceipt').textContent=names.length?'Seen by '+names.slice(0,4).join(', ')+(names.length>4?' + more':''):'';}
  async function poll(){
    if(inFlight)return;inFlight=true;clearTimeout(timer);
    try{const response=await fetch(app.dataset.feedUrl,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error();const data=await response.json();const first=!initialized;merge(data.messages||[]);if(first)stream.scrollTop=stream.scrollHeight;older.hidden=oldestExhausted||!data.has_more&&!loadingOlder;readers(data);failures=0;connection.textContent='● Connected';connection.dataset.state='online';markRead();}
    catch{failures++;connection.textContent=navigator.onLine?'Reconnecting… your draft is safe':'Offline · your draft is safe';connection.dataset.state='offline';}
    finally{inFlight=false;timer=setTimeout(poll,document.hidden?25000:Math.min(3000*2**failures,30000));}
  }
  older.onclick=async()=>{if(loadingOlder)return;const before=Math.min(...messages.keys());if(!Number.isFinite(before))return;loadingOlder=true;older.disabled=true;try{const response=await fetch(`${app.dataset.feedUrl}?before=${before}`,{cache:'no-store',signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error();const data=await response.json();merge(data.messages,{prepend:true});oldestExhausted=!data.has_more;older.hidden=oldestExhausted;}catch{showError('Earlier messages could not be loaded. Try again.');}finally{loadingOlder=false;older.disabled=false;}};
  stream.addEventListener('scroll',()=>{if(nearBottom()){jump.hidden=true;markRead();}},{passive:true});jump.onclick=()=>{stream.scrollTo({top:stream.scrollHeight,behavior:'smooth'});};
  stream.addEventListener('click',async event=>{const b=event.target.closest('[data-reaction]');if(!b)return;b.disabled=true;try{await post(app.dataset.reactTemplate.replace('/0/',`/${b.dataset.messageId}/`),formData({emoji:b.dataset.reaction}));b.closest('details')?.removeAttribute('open');await poll();}catch(e){showError(e.message);}finally{b.disabled=false;}});
  if(composer){
    const sendButton=document.getElementById('sendTeamMessage');
    function filesChanged(){const preview=document.getElementById('chatFiles');preview.replaceChildren();Array.from(fileInput.files).forEach(file=>preview.append(text('span','📎 '+file.name)));if(fileInput.files.length){const b=text('button','Clear files');b.type='button';b.onclick=()=>{fileInput.value='';filesChanged();};preview.append(b);}}
    fileInput.onchange=filesChanged;
    composer.onsubmit=async event=>{
      event.preventDefault();if(sending)return;if(!textarea.value.trim()&&!fileInput.files.length&&!pendingForm)return;
      if(fileInput.files.length>6||Array.from(fileInput.files).some(f=>f.size>15*1024*1024)){showError('Attach up to 6 files, with a maximum of 15 MB each.');return;}
      sending=true;sendButton.disabled=true;sendButton.textContent='Sending…';textarea.readOnly=true;fileInput.disabled=true;showError('');
      if(!pendingForm){nonce=crypto.randomUUID();pendingForm=new FormData();pendingForm.append('body',textarea.value);pendingForm.append('nonce',nonce);Array.from(fileInput.files).forEach(f=>pendingForm.append('attachments',f));}
      try{const result=await post(app.dataset.sendUrl,pendingForm);merge([result.message]);stream.scrollTop=stream.scrollHeight;textarea.value='';fileInput.value='';pendingForm=null;nonce=null;filesChanged();textarea.readOnly=false;fileInput.disabled=false;markRead();window.dispatchEvent(new Event('team-chat-sent'));}
      catch(e){if(e.definite){pendingForm=null;nonce=null;textarea.readOnly=false;fileInput.disabled=false;showError(e.message);}else showError(e.message+' Press Retry send to check or retry the same message without duplicating it.');}
      finally{sending=false;sendButton.disabled=false;sendButton.textContent=pendingForm?'Retry send ↻':'Send ↑';if(!pendingForm)textarea.focus();}
    };
    textarea.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();composer.requestSubmit();}});
    app.querySelectorAll('[data-insert-emoji]').forEach(b=>b.onclick=()=>{if(textarea.readOnly)return;textarea.setRangeText(b.dataset.insertEmoji+' ',textarea.selectionStart,textarea.selectionEnd,'end');b.closest('details').open=false;textarea.focus();});
    window.addEventListener('beforeunload',e=>{if(textarea.value.trim()||fileInput.files.length||pendingForm){e.preventDefault();e.returnValue='';}});
  }
  document.getElementById('chatSidebarSearch').oninput=e=>{const q=e.target.value.toLowerCase();app.querySelectorAll('.chat-side-thread').forEach(a=>a.hidden=!a.textContent.toLowerCase().includes(q));};
  const mute=document.getElementById('muteChat');if(mute)mute.onclick=async()=>{mute.disabled=true;try{const r=await post(app.dataset.muteUrl,formData({muted:mute.dataset.muted==='true'?'false':'true'}));mute.dataset.muted=String(r.muted);mute.setAttribute('aria-pressed',String(r.muted));mute.textContent=r.muted?'Unmute':'Mute';window.dispatchEvent(new Event('team-chat-read'));}catch(e){showError(e.message);}finally{mute.disabled=false;}};
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});window.addEventListener('focus',()=>{markRead();poll();});window.addEventListener('online',poll);
  stream.scrollTop=stream.scrollHeight;poll();
})();
