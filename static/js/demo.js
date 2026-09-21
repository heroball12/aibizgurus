(() => {
  const $ = id => document.getElementById(id), app = $('demoApp');
  if (!app) return;
  const industries = JSON.parse($('demo-industries').textContent);
  const histories = JSON.parse($('demo-history').textContent);
  const config = JSON.parse($('demo-config').textContent);
  const transferFor = slug => config.handoff?.industry === slug ? config.handoff : null;
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  const featured = industries.map(item => item.slug);
  const modes = {}, drafts = {};
  let selected = null, pending = null, resetting = false, browsingAll = false, videoFrame = null, switching = false;
  let closeResolve = null, handoffResolve = null;
  const guided = new URLSearchParams(location.search).get('guided') === '1' && parent !== window;
  const error = message => { $('demoChatError').textContent = message; $('demoChatError').hidden = !message; };
  function listIndustries() {
    const query = $('industrySearch').value.trim().toLowerCase(), category = $('industryCategory').value;
    let list = industries.filter(item => (!category || item.category === category) && `${item.industry} ${item.category} ${item.services} ${item.covers.join(" ")}`.toLowerCase().includes(query));
    const popular = !query && !category && !browsingAll;
    if (popular) list = featured.map(slug => list.find(item => item.slug === slug)).filter(Boolean);
    if (popular && selected && !list.some(item => item.slug === selected.slug)) list.push(selected);
    $('industryList').replaceChildren();
    $('industryList').classList.toggle('expanded', browsingAll || !!query || !!category);
    for (const item of list) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'demo-industry';
      button.dataset.industry = item.slug; button.setAttribute('aria-pressed', String(selected?.slug === item.slug));
      const image = document.createElement('img'); image.src = item.portrait; image.alt = ''; image.loading = 'lazy';
      const label = document.createElement('span'), title = document.createElement('strong'), name = document.createElement('small'), arrow = document.createElement('b');
      title.textContent = item.industry; name.textContent = `Meet ${item.name}`; arrow.textContent = '↗'; arrow.setAttribute('aria-hidden', 'true');
      label.append(title, name); button.append(image, label, arrow); button.addEventListener('click', () => selectIndustry(item, true));
      $('industryList').append(button);
    }
    $('noIndustries').hidden = list.length > 0;
    $('industryResults').textContent = popular ? '' : String(list.length);
    $('industryListTitle').textContent = popular ? 'MEET THE TEAM' : 'MATCHING CATEGORIES';
    $('browseAll').hidden = !popular;
  }
  function bubble(role, text, typing = false, topicIds = []) {
    const node = document.createElement('div'); node.className = `demo-message ${role}${typing ? ' typing' : ''}`;
    const label = document.createElement('small'), body = document.createElement('p');
    label.textContent = role === 'user' ? 'YOU' : `${selected.name.toUpperCase()} / AI EMPLOYEE`; body.textContent = text;
    node.append(label, body);
    if (role === 'assistant' && selected.knowledge && Array.isArray(topicIds)) {
      const topics = selected.knowledge.topics.filter(topic => topicIds.includes(topic.id)).slice(0,3);
      if(topics.length){
        const reading=document.createElement('div');reading.className='demo-reading';
        const heading=document.createElement('span');heading.textContent='Related reading';reading.append(heading);
        for(const topic of topics){const link=document.createElement('a');link.textContent=topic.title;link.href=selected.knowledge.url+'#'+topic.id;link.target='_blank';link.rel='noopener';reading.append(link);}
        node.append(reading);
      }
    }
    $('tryMessages').append(node);
  }
  function renderChat() {
    $('tryMessages').replaceChildren(); bubble('assistant', selected.greeting);
    for (const turn of histories[selected.slug] || []) bubble(turn.role === 'user' ? 'user' : 'assistant', turn.content, false, turn.knowledge_topics);
    if (pending?.slug === selected.slug) { bubble('user', pending.message); bubble('assistant', `${selected.name} is thinking…`, true); }
    $('tryMessages').scrollTop = $('tryMessages').scrollHeight;
    const mode = modes[selected.slug] || (config.aiAvailable ? 'ready' : 'guided');
    $('replyMode').textContent = mode === 'guided' ? 'GUIDED PREVIEW' : mode === 'ai' ? 'LIVE AI CHAT' : 'AI CHAT';
    $('modeNote').textContent = mode === 'guided' ? (selected.knowledge ? 'Reference preview: replies come from reviewed notes. Try video for a live conversation.' : 'Live AI is unavailable right now. These are sample replies; try video for a live conversation.') : 'AI replies can be imperfect. Use sample details. Enter to send; Shift + Enter for a new line.';
    $('clearChat').disabled = !!pending || resetting;
    $('demoSend').disabled = !!pending || resetting;
    $('demoMessage').disabled = resetting;
    $('demoSend').setAttribute('aria-label', pending ? 'Waiting for reply' : 'Send message');
    $('tryMessages').setAttribute('aria-busy', String(pending?.slug === selected.slug));
    $('suggestedPrompts').replaceChildren();
    if (!(histories[selected.slug]?.length) && pending?.slug !== selected.slug) {
      for (const text of selected.prompts) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = text; button.disabled = !!pending;
        button.addEventListener('click', () => { $('demoMessage').value = text; $('demoChatForm').requestSubmit(); });
        $('suggestedPrompts').append(button);
      }
    }
  }
  async function closeVideo() {
    if (!videoFrame) return true;
    $('videoNotice').textContent = 'Closing the video conversation…';
    const result = await new Promise(resolve => {
      const timer = setTimeout(() => { closeResolve = null; resolve(false); }, 30000);
      closeResolve = ok => { clearTimeout(timer); closeResolve = null; resolve(ok); };
      videoFrame.contentWindow.postMessage({source:'aibg-demo-host', type:'close'}, location.origin);
    });
    if (!result) { $('videoNotice').textContent = 'Please end the call in the video window, then try switching again.'; return false; }
    videoFrame.remove(); videoFrame = null; return true;
  }
  function textView() {
    $('textExperience').hidden = false; $('videoExperience').hidden = true;
    $('textMode').setAttribute('aria-pressed','true'); $('videoMode').setAttribute('aria-pressed','false');
  }
  async function selectIndustry(item, focus = false) {
    if (switching || !item || (selected?.slug === item.slug && focus)) return;
    switching = true;
    try {
      if (!(await closeVideo())) return;
      if (selected) drafts[selected.slug] = $('demoMessage').value;
      selected = item; textView(); error('');
      $('employeeTitle').textContent = item.industry; $('employeeCategory').textContent = item.category;
      $('employeeBusiness').textContent = item.business; $('employeeName').textContent = item.name.toUpperCase();
      $('employeeServices').textContent = item.services; $('employeePortrait').src = item.portrait; $('employeePortrait').alt = item.portrait_alt;
      $('employeeKnowledge').hidden=!item.knowledge;
      if(item.knowledge){$('employeeKnowledgeLink').href=item.knowledge.url;$('employeeKnowledgeDate').textContent='References checked '+item.knowledge.reviewed_on;}
      $('scenarioSignup').href = item.signup_url; $('demoMessage').value = drafts[item.slug] || '';
      $('demoMessage').placeholder = `Ask ${item.name} as a customer…`;
      listIndustries(); renderChat();
      const url = new URL(location.href); url.searchParams.set('industry',item.slug); if(!transferFor(item.slug))url.searchParams.delete('handoff'); history.replaceState(null,'',url);
      if (focus && matchMedia('(max-width: 650px)').matches) { $('employeePanel').scrollIntoView({behavior:'smooth',block:'start'}); $('employeePanel').focus({preventScroll:true}); }
    } finally { switching = false; }
  }
  async function videoView() {
    if (!selected || switching || videoFrame) return;
    switching = true;
    $('textExperience').hidden = true; $('videoExperience').hidden = false;
    $('textMode').setAttribute('aria-pressed','false'); $('videoMode').setAttribute('aria-pressed','true');
    try {
      if (!selected.video_available) { $('videoNotice').textContent = 'This video employee is not connected yet. You can explore this industry in text chat.'; return; }
      if (guided) {
        $('videoNotice').textContent = 'Guru is handing you over to your demo employee…';
        const ready = await new Promise(resolve => {
          const timer = setTimeout(() => { handoffResolve = null; resolve(false); },65000);
          handoffResolve = ok => { clearTimeout(timer); handoffResolve = null; resolve(ok); };
          parent.postMessage({source:'aibg-guided-page',type:'demo-handoff',industry:selected.slug,handoff:transferFor(selected.slug)?.id},location.origin);
        });
        if (!ready) { $('videoNotice').textContent = 'Guru’s call could not close yet. End Guru’s call, then return to text chat and choose video again.'; return; }
      }
      const transfer=transferFor(selected.slug);
      $('videoNotice').textContent = transfer ? `Guru has introduced you. ${selected.name} is joining with your name and request. You can type or speak.` : `Meet ${selected.name}, your ${selected.industry.toLowerCase()} employee. Start a new video conversation below. You can type or speak; your camera stays off.`;
      videoFrame = document.createElement('iframe'); videoFrame.title = `${selected.name} — ${selected.industry} live video demo`;
      videoFrame.allow = 'microphone; autoplay'; const url=new URL(selected.video_url,location.origin);if(transfer)url.searchParams.set('handoff',transfer.id);videoFrame.src = url.href;
      $('demoVideoMount').replaceChildren(videoFrame);
    } finally { switching = false; }
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin) return;
    if (event.source === videoFrame?.contentWindow && event.data?.source === 'aibg-demo-employee') {
      if(event.data.type==='resize' && Number.isFinite(event.data.height))videoFrame.style.height=Math.max(380,Math.min(1800,event.data.height))+'px';
      if (event.data.type === 'ready' && closeResolve) videoFrame.contentWindow.postMessage({source:'aibg-demo-host',type:'close'},location.origin);
      if (event.data.type === 'closed') closeResolve?.(true);
      if (event.data.type === 'close') {
        if (closeResolve) closeResolve(true);
        else { videoFrame.remove(); videoFrame = null; textView(); }
      }
    }
    if (event.source === parent && event.data?.source === 'aibg-concierge' && event.data.type === 'demo-handoff-ready') handoffResolve?.(event.data.ok === true);
  });
  async function post(data) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(),35000);
    try {
      const response = await fetch(app.dataset.chatUrl, {method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':csrf},body:new URLSearchParams(data),signal:controller.signal});
      let result; try { result = await response.json(); } catch (_) { throw new Error('The connection was interrupted. Your message is still in the box; please try again.'); }
      if (!response.ok) throw new Error(result.error || 'The message could not be sent. Please try again.');
      return result;
    } finally { clearTimeout(timer); }
  }
  $('demoChatForm').addEventListener('submit', async event => {
    event.preventDefault(); const message = $('demoMessage').value.trim(); if (!message || pending || resetting) return;
    const slug = selected.slug; pending = {slug,message}; $('demoMessage').value = ''; drafts[slug] = ''; error(''); renderChat();
    try {
      const result = await post({industry:slug,message,...(transferFor(slug)?{handoff:transferFor(slug).id}:{})});
      if (result.industry !== slug || typeof result.reply !== 'string') throw new Error('The reply could not be matched to this industry. Please try again.');
      histories[slug] = [...(histories[slug] || []), {role:'user',content:message}, {role:'assistant',content:result.reply,knowledge_topics:result.knowledge_topics}].slice(-12); modes[slug] = result.mode;
    } catch (err) {
      drafts[slug] = message;
      if (selected.slug === slug) { if (!$('demoMessage').value) $('demoMessage').value = message; error(err.name === 'AbortError' ? 'The reply took too long. Please refresh before retrying to recover any completed reply.' : err.message); }
    } finally { pending = null; renderChat(); }
  });
  $('demoMessage').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('demoChatForm').requestSubmit(); } });
  $('clearChat').addEventListener('click', async () => {
    if (pending || resetting) return; const slug = selected.slug; resetting = true; error(''); renderChat();
    try { await post({industry:slug,reset:'1'}); histories[slug] = []; delete modes[slug]; }
    catch (err) { if (selected.slug === slug) error(err.message); }
    finally { resetting = false; renderChat(); }
  });
  $('industrySearch').addEventListener('input',listIndustries); $('industryCategory').addEventListener('change',listIndustries);
  $('browseAll').addEventListener('click', () => { browsingAll = true; listIndustries(); $('industrySearch').focus(); });
  for (const id of ['videoMode','meetVideo']) $(id).addEventListener('click',videoView);
  for (const id of ['textMode','backToText']) $(id).addEventListener('click', async () => { if (switching) return; switching = true; try { if (await closeVideo()) textView(); } finally { switching = false; } });
  const slug = new URLSearchParams(location.search).get('industry');
  selectIndustry(industries.find(item => item.slug === slug || item.industry_slugs.includes(slug)) || industries.find(item => item.slug === 'food-hospitality') || industries[0]).then(()=>{if(guided && transferFor(selected.slug))videoView();});
})();
