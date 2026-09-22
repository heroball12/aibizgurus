(() => {
  const root=document.getElementById('teamNotificationCenter');if(!root)return;
  const el=id=>document.getElementById(id),tray=el('teamNotificationTray'),dialog=el('teamNotificationSettings'),form=el('notificationSettingsForm');
  const csrf=root.querySelector('[name=csrfmiddlewaretoken]').value,baseTitle=document.title,storageKey=`aibg-chat-notified-${root.dataset.user}`;
  let prefs={sound:'aurora',volume:40,desktop:false,previews:true,snoozed_until:null},timer,inFlight=false,failures=0,initialized=false,audio=null,toastTimer,settingsBusy=false,lastSummary=null;
  const text=(tag,value,cls)=>{const e=document.createElement(tag);e.textContent=value??'';if(cls)e.className=cls;return e;};
  function getStored(){try{return Number(localStorage.getItem(storageKey)||0);}catch{return 0;}}
  function putStored(id){try{localStorage.setItem(storageKey,String(id));}catch{}}
  function audioReady(){const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)return null;if(!audio)audio=new Audio();if(audio.state==='suspended')audio.resume().catch(()=>{});return audio;}
  function sound(name=prefs.sound,volume=prefs.volume){if(name==='none'||volume===0)return;const context=audioReady();if(!context||context.state!=='running')return;const notes={aurora:[660,990],glass:[1318],pulse:[440,440],soft:[523,659,784]}[name]||[660,990];const start=context.currentTime+.02;notes.forEach((frequency,index)=>{const oscillator=context.createOscillator(),gain=context.createGain(),at=start+index*.12;oscillator.type='sine';oscillator.frequency.value=frequency;gain.gain.setValueAtTime(.0001,at);gain.gain.exponentialRampToValueAtTime(Math.max(.0001,volume/100*.14),at+.018);gain.gain.exponentialRampToValueAtTime(.0001,at+.38);oscillator.connect(gain);gain.connect(context.destination);oscillator.start(at);oscillator.stop(at+.4);oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};});}
  function setOpen(open){tray.hidden=!open;el('teamBell').setAttribute('aria-expanded',String(open));if(open){audioReady();poll();}else el('teamBell').focus();}
  function toast(alert){const node=el('teamNotificationToast');node.replaceChildren(text('strong',alert.title),text('span',prefs.previews?`${alert.sender}: ${alert.body}`:'New message from your team'));node.href=alert.url;node.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.hidden=true,7000);}
  function notify(alerts){
    const newest=Math.max(0,...alerts.map(a=>a.id));
    if(!initialized){initialized=true;putStored(Math.max(getStored(),newest));return;}
    const act=()=>{const previous=getStored();if(newest<=previous)return;putStored(newest);
      if(prefs.snoozed_until&&Date.parse(prefs.snoozed_until)>Date.now())return;
      const active=document.querySelector('#teamChatApp')?.dataset.threadId;
      const fresh=alerts.filter(a=>a.id>previous&&!(String(a.thread_id)===active&&!document.hidden&&document.hasFocus())).sort((a,b)=>b.id-a.id);
      if(!fresh.length)return;const alert=fresh[0];sound();toast(alert);
      if(prefs.desktop&&'Notification' in window&&Notification.permission==='granted')try{const notification=new Notification(alert.title,{body:prefs.previews?`${alert.sender}: ${alert.body}`:'New team message',tag:`aibg-chat-${alert.thread_id}`,icon:root.dataset.icon,silent:true});notification.onclick=()=>{window.focus();location.assign(alert.url);notification.close();};}catch{}
    };
    if(navigator.locks)navigator.locks.request(`aibg-chat-alert-${root.dataset.user}`,{ifAvailable:true},lock=>{if(lock)act();}).catch(()=>{});else act();
  }
  function render(data){
    lastSummary=data;prefs=data.preferences||prefs;const count=data.unread_count||0;el('teamUnreadBadge').hidden=!count;el('teamUnreadBadge').textContent=count>99?'99+':count;document.title=count?`(${count}) ${baseTitle}`:baseTitle;
    const inbox=el('inboxUnread');if(inbox)inbox.textContent=count?`${count} unread`:'';
    for(const item of document.querySelectorAll('[data-thread-id]')){const current=(data.threads||[]).find(t=>String(t.id)===item.dataset.threadId),badge=item.querySelector('[data-thread-unread]');if(badge){badge.hidden=!current?.unread_count;badge.textContent=current?.unread_count||'';}}
    const list=el('teamNotificationList');list.replaceChildren();
    if(!data.threads?.length)list.append(text('p','No conversations yet. Start one in Teamspace.'));
    for(const thread of data.threads||[]){const a=text('a','',thread.unread_count?'team-notification-item unread':'team-notification-item');a.href=thread.url;a.append(text('span',thread.title.slice(0,1).toUpperCase(),'notification-avatar'));const copy=text('span','','notification-copy');copy.append(text('strong',thread.title),text('small',prefs.previews?thread.last_body:'Open conversation'));a.append(copy);if(thread.unread_count)a.append(text('b',thread.unread_count));else if(thread.muted)a.append(text('small','Muted'));list.append(a);}
    el('notificationSyncState').textContent=prefs.snoozed_until?`Paused until ${new Date(prefs.snoozed_until).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}`:'Up to date';
    notify(data.alerts||[]);
  }
  async function poll(){if(inFlight)return;inFlight=true;clearTimeout(timer);try{const response=await fetch(root.dataset.summaryUrl,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error();render(await response.json());failures=0;}catch{failures++;el('notificationSyncState').textContent=navigator.onLine?'Reconnecting…':'Offline';}finally{inFlight=false;timer=setTimeout(poll,document.hidden?25000:Math.min(7000*2**failures,45000));}}
  async function post(url,body){const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':csrf},body,signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error('Could not save. Check your connection or sign in again.');return response.json();}
  function permissionText(){el('desktopPermissionState').textContent=!('Notification'in window)?'Desktop alerts are not supported in this browser.':Notification.permission==='granted'?'This browser allows desktop alerts.':Notification.permission==='denied'?'Desktop alerts are blocked. You can enable them in your browser’s site settings.':'Choose Enable alerts to allow notifications in this browser.';}
  function openSettings(){
    el('notificationSound').value=prefs.sound;el('notificationVolume').value=prefs.volume;el('notificationVolumeValue').textContent=prefs.volume+'%';el('notificationDesktop').checked=prefs.desktop;el('notificationPreviews').checked=prefs.previews;el('notificationSnooze').value='-1';el('notificationSnoozeState').textContent=prefs.snoozed_until?'Paused until '+new Date(prefs.snoozed_until).toLocaleString():'Notifications are on.';el('notificationSettingsStatus').textContent='';permissionText();dialog.showModal();
  }
  document.querySelectorAll('[data-notification-settings]').forEach(b=>b.addEventListener('click',openSettings));
  el('closeNotificationSettings').onclick=()=>dialog.close();el('closeNotificationTray').onclick=()=>setOpen(false);el('teamBell').onclick=()=>setOpen(tray.hidden);
  el('previewNotificationSound').onclick=async()=>{const c=audioReady();if(c)await c.resume();sound(el('notificationSound').value,Number(el('notificationVolume').value));};
  el('notificationVolume').oninput=()=>el('notificationVolumeValue').textContent=el('notificationVolume').value+'%';
  el('enableDesktopAlerts').onclick=async()=>{audioReady();if('Notification'in window){const result=await Notification.requestPermission();el('notificationDesktop').checked=result==='granted';permissionText();}};
  form.onsubmit=async event=>{event.preventDefault();if(settingsBusy)return;settingsBusy=true;const button=form.querySelector('[type=submit]');button.disabled=true;const f=new FormData(form);f.set('desktop',String(el('notificationDesktop').checked));f.set('previews',String(el('notificationPreviews').checked));try{prefs=await post(root.dataset.prefsUrl,f);el('notificationSettingsStatus').textContent='Preferences saved.';await poll();}catch(e){el('notificationSettingsStatus').textContent=e.message;}finally{settingsBusy=false;button.disabled=false;}};
  el('markAllChatRead').onclick=async()=>{const b=el('markAllChatRead');b.disabled=true;try{await post(root.dataset.readAllUrl,new FormData());await poll();}catch(e){el('notificationSyncState').textContent=e.message;}finally{b.disabled=false;}};
  document.addEventListener('pointerdown',audioReady,{once:true,passive:true});document.addEventListener('keydown',audioReady,{once:true});
  document.addEventListener('click',event=>{if(!tray.hidden&&!root.contains(event.target)&&!event.target.closest('[data-notification-settings]'))setOpen(false);});document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!tray.hidden&&!dialog.open)setOpen(false);});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});window.addEventListener('online',poll);window.addEventListener('team-chat-read',poll);window.addEventListener('team-chat-sent',poll);poll();
})();
