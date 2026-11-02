(() => {
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || document.getElementById('academyPlayer')?.dataset.csrf;
  async function post(url, data) {
    let response;
    try {
      response = await fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':csrf()}, body:JSON.stringify(data), signal:AbortSignal.timeout(60000)});
    } catch {
      throw new Error('The connection was interrupted. Keep this page open and try again.');
    }
    let result;
    try { result=await response.json(); } catch { result=null; }
    let message;
    if(response.redirected || response.status===401) message='Your sign-in expired. Sign in again in another tab, then retry here.';
    else if(response.status>=500) message='The training server could not save this request. Keep this page open and try again; this is not a grading result.';
    else if(response.status===403) message=result?.error || 'Your sign-in or security token needs refreshing. Reload this page, then try again.';
    else if(!response.ok) message=result?.error || 'This request could not be saved. Please try again.';
    else if(!result || typeof result!=='object') message='The training server returned an unexpected response. Keep this page open and try again.';
    if(message) {const error=new Error(message);error.status=response.status;throw error;}
    return result;
  }
  const player=document.getElementById('academyPlayer'),video=document.getElementById('lessonVideo');
  if(video) {
    let anchor=0,sending=false,restored=false,seeked=false;
    const status=document.getElementById('watchStatus'),error=document.getElementById('playerError');
    const update=async()=>{
      if(sending || player.dataset.official!=='true' || !Number.isFinite(video.currentTime))return;
      sending=true;const position=video.currentTime;
      try { const result=await post(player.dataset.progressUrl,{session:player.dataset.session,start:anchor,position,playing:!video.paused&&!document.hidden&&!seeked});anchor=position;seeked=false;status.textContent=result.credited_video?result.label:`${result.percent}% watched · ${result.label}`; }
      catch(e){status.textContent='Progress could not sync. Keep this page open to retry.';}
      finally{sending=false;}
    };
    video.addEventListener('loadedmetadata',()=>{if(!restored){video.currentTime=Math.min(Number(player.dataset.position)||0,video.duration);restored=true;}anchor=video.currentTime;update();});
    video.addEventListener('seeking',()=>{seeked=true;});video.addEventListener('seeked',update);
    video.addEventListener('play',update);video.addEventListener('pause',update);video.addEventListener('ended',update);
    video.addEventListener('error',()=>{error.hidden=false;error.textContent='The video could not load. Reload it to renew access, or continue with the transcript.';});
    document.getElementById('lessonSpeed').onchange=e=>{const rate=Number(e.target.value);video.defaultPlaybackRate=rate;video.playbackRate=rate;};
    document.getElementById('retryVideo').onclick=()=>{const position=video.currentTime;video.querySelector('source').src=video.querySelector('source').src.split('?')[0]+'?renew='+Date.now();video.load();video.addEventListener('loadedmetadata',()=>{video.currentTime=position;},{once:true});error.hidden=true;};
    setInterval(update,5000);document.addEventListener('visibilitychange',update);
    document.querySelectorAll('[data-seek]').forEach(b=>b.onclick=e=>{e.preventDefault();video.currentTime=Number(b.dataset.seek);video.focus();});
  }
  document.getElementById('printJobAid')?.addEventListener('click',()=>window.print());
  const quiz=document.getElementById('academyQuiz');
  if(quiz) {
    const button=quiz.querySelector('button'),result=document.getElementById('quizResult');
    const radios=Array.from(quiz.querySelectorAll('input[type="radio"]'));
    const draftKey=quiz.dataset.draftKey;
    let submitted=false;
    const answers=()=>Object.fromEntries(radios.filter(r=>r.checked).map(r=>[r.name.slice(2),Number(r.value)]));
    const saveDraft=()=>{
      try {if(draftKey)sessionStorage.setItem(draftKey,JSON.stringify({answers:answers(),nonce:quiz.dataset.nonce,submitted}));} catch {}
    };
    try {
      const saved=draftKey && JSON.parse(sessionStorage.getItem(draftKey));
      if(saved?.answers && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(saved.nonce)) {
        for(const radio of radios) radio.checked=saved.answers[radio.name.slice(2)]===Number(radio.value);
        quiz.dataset.nonce=saved.nonce;submitted=saved.submitted===true;
        result.textContent='Your selected answers were restored. Check them, then submit when ready.';
      }
    } catch {}
    quiz.addEventListener('change',()=>{
      if(submitted){quiz.dataset.nonce=crypto.randomUUID();submitted=false;}
      saveDraft();
    });
    quiz.addEventListener('submit',async event=>{
      event.preventDefault();if(button.disabled || !quiz.reportValidity())return;
      const payload={answers:answers(),nonce:quiz.dataset.nonce};
      submitted=true;saveDraft();button.disabled=true;
      radios.forEach(r=>r.disabled=true);result.textContent='Checking your decisions…';
      try {
        const data=await post(quiz.dataset.url,payload);
        result.replaceChildren();const title=document.createElement('h3');
        title.textContent=`${data.score}% — ${data.passed?'Knowledge check passed':'Not passed yet — review the feedback below'}`;result.append(title);
        for(const item of data.feedback){const box=document.createElement('div'),heading=document.createElement('p'),detail=document.createElement('p');heading.textContent=(item.is_correct?'✓ ':'↻ ')+item.question;detail.textContent=`Your choice: ${item.selected}. Strongest choice: ${item.correct}. ${item.explanation}`;box.append(heading,detail);result.append(box);}
        quiz.dataset.nonce=crypto.randomUUID();submitted=false;button.textContent='Submit another attempt';
        try {if(draftKey)sessionStorage.removeItem(draftKey);} catch {}
      } catch(e){result.textContent=e.message+' Your selected answers have been kept.';}
      finally{button.disabled=false;radios.forEach(r=>r.disabled=false);}
    });
  }
  const form=document.getElementById('practiceForm');
  if(form){let pending=null,sending=false;const input=document.getElementById('practiceMessage'),status=document.getElementById('practiceStatus'),button=form.querySelector('button'),stream=document.getElementById('practiceTranscript');
    form.onsubmit=async event=>{event.preventDefault();if(sending)return;if(!pending)pending={message:input.value,nonce:crypto.randomUUID()};sending=true;input.readOnly=true;button.disabled=true;status.textContent='Guru is responding…';
      try{const data=await post(form.dataset.url,pending);stream.replaceChildren();for(const message of data.transcript){const item=document.createElement('article'),label=document.createElement('strong'),body=document.createElement('p');item.className=message.role;label.textContent=message.role==='user'?'You':'Guru / simulated prospect';body.textContent=message.content;item.append(label,body);stream.append(item);}stream.scrollTop=stream.scrollHeight;input.value='';pending=null;input.readOnly=false;status.textContent=data.guided?'Guided rehearsal · scripted prospect replies':'Your turn';input.focus();}
      catch(e){status.textContent=e.message+' Retry sends the same response without duplicating it.';if(e.status===400||e.status===403){pending=null;input.readOnly=false;}}
      finally{sending=false;button.disabled=false;button.textContent=pending?'Retry response ↻':'Send response ↑';}
    };
    window.addEventListener('beforeunload',e=>{if(pending||input.value.trim()){e.preventDefault();e.returnValue='';}});
  }
})();
