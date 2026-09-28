(() => {
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || document.getElementById('academyPlayer')?.dataset.csrf;
  async function post(url, data) {
    const response = await fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':csrf()}, body:JSON.stringify(data), signal:AbortSignal.timeout(60000)});
    let result;
    try { result=await response.json(); } catch { throw new Error('Your session or connection needs attention. Reload after saving your work.'); }
    if (!response.ok) { const error=new Error(result.error || 'Please try again.');error.status=response.status;throw error; }
    return result;
  }
  const player=document.getElementById('academyPlayer'),video=document.getElementById('lessonVideo');
  if(video) {
    let anchor=0,sending=false,restored=false,seeked=false;
    const status=document.getElementById('watchStatus'),error=document.getElementById('playerError');
    const update=async()=>{
      if(sending || player.dataset.official!=='true' || !Number.isFinite(video.currentTime))return;
      sending=true;const position=video.currentTime;
      try { const result=await post(player.dataset.progressUrl,{session:player.dataset.session,start:anchor,position,playing:!video.paused&&!document.hidden&&!seeked});anchor=position;seeked=false;status.textContent=`${result.percent}% watched · ${result.label}`; }
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
  if(quiz) quiz.addEventListener('submit',async event=>{
    event.preventDefault();if(!quiz.reportValidity())return;const button=quiz.querySelector('button'),result=document.getElementById('quizResult');if(button.disabled)return;button.disabled=true;result.textContent='Checking your decisions…';
    const answers={};new FormData(quiz).forEach((v,k)=>{if(k.startsWith('q_'))answers[k.slice(2)]=Number(v);});
    try {const data=await post(quiz.dataset.url,{answers,nonce:quiz.dataset.nonce});result.replaceChildren();const title=document.createElement('h3');title.textContent=`${data.score}% — ${data.passed?'Knowledge check passed':'Review, then try again'}`;result.append(title);
      for(const item of data.feedback){const box=document.createElement('div'),heading=document.createElement('p'),detail=document.createElement('p');heading.textContent=(item.is_correct?'✓ ':'↻ ')+item.question;detail.textContent=`Your choice: ${item.selected}. Strongest choice: ${item.correct}. ${item.explanation}`;box.append(heading,detail);result.append(box);}
      quiz.dataset.nonce=crypto.randomUUID();button.textContent='Submit another attempt';
    } catch(e){result.textContent=e.message;}finally{button.disabled=false;}
  });
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
