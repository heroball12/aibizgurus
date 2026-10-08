(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('experienceConfig').textContent);
  const $=id=>document.getElementById(id), csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;
  let session=null, booting=null, busy=false, mode='text', epoch=0, voiceCycle=0, failed=null, pendingScenario=null, state='READY', compared=new Set(), financeShown=null;
  const storeKey=config.ipadApp?'aibg:velocity-ipad-session:v1':'aibg:velocity-session:v1';
  const storage=config.ipadApp?localStorage:sessionStorage;
  let nativeSuspended=false;
  const notifyNative=()=>{if(config.ipadApp)window.dispatchEvent(new CustomEvent('guru:state',{detail:{screen:'customer',ready:!!session,busy,state,crmURL:session?location.origin+config.crmUrl+'?session='+encodeURIComponent(session.id):null}}));};
  const money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n);
  const node=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
  const notice=(message='')=>{$('connectionNotice').textContent=message;$('connectionNotice').hidden=!message;};
  function setState(next,hint='') {state=next;$('aiState').textContent=next;$('voiceHint').textContent=hint;$('micButton').textContent=next==='LISTENING'?'■ Finish speaking':'◉ Start listening';$('interrupt').hidden=next!=='SPEAKING';$('micButton').disabled=busy||next==='SPEAKING';notifyNative();}
  const voice=new ExperienceVoice({onAudio:transcribe,onState:setState,onError:message=>{setState('READY','Microphone is off');notice(message);if(session)action('voice_error').catch(()=>{});},onLevel:value=>document.documentElement.style.setProperty('--voice-level',value.toFixed(3))});
  function stopVoice(){++voiceCycle;voice.stop();}
  function listen(){if(document.hidden)return;nativeSuspended=false;++voiceCycle;return voice.listen();}
  async function api(url,data,options={}) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),options.timeout||65000);
    try {
      const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':csrf,'Content-Type':options.raw?options.mime:'application/json'},body:options.raw?data:JSON.stringify(data),signal:controller.signal});
      if(!response.ok){let result;try{result=await response.json();}catch{}const e=new Error(result?.error||(response.status===404?'This demo session ended. Tap New prospect to start fresh.':'Connection interrupted. Please retry.'));e.code=result?.code;e.status=response.status;e.fields=result?.errors;if(config.ipadApp&&e.code==='signin_required'){stopVoice();location.assign(config.base);}throw e;}
      return options.audio?response:await response.json();
    } catch(e) {if(e.name==='AbortError')throw new Error('This reply took too long. Your conversation is saved; please retry.');if(e instanceof TypeError)throw new Error('Connection interrupted — reconnecting… Check your connection, then tap Retry.');throw e;}
    finally{clearTimeout(timer);}
  }
  async function boot({fresh=false,scenario}={}) {
    if(session&&!fresh)return session;
    if(booting&&!fresh)return booting;
    const current=epoch;
    booting=(async()=>{
      let previous;try{previous=JSON.parse(storage.getItem(storeKey));}catch{}
      let result;
      if(!fresh&&previous?.ref===config.ref&&previous?.id){try{result=await api(config.sessionUrl,{resume:previous.id});}catch(e){if(e.status!==404)throw e;}}
      if(!result)result=await api(config.sessionUrl,{scenario:scenario||config.scenario,ref:config.ref});
      if(current!==epoch)return null;
      session=result;try{storage.setItem(storeKey,JSON.stringify({id:result.id,ref:config.ref}));}catch{}
      render(result);return result;
    })();
    try{return await booting;}finally{booting=null;}
  }
  async function action(name,extra={}) {await boot();return api(config.actionUrl,{session:session.id,action:name,...extra});}
  function activate(){document.body.classList.add('ex-active');window.scrollTo({top:0,behavior:'smooth'});}
  function appendMessage(role,text,extra='') {const item=node('div',`ex-message ${role} ${extra}`);item.append(node('small','',role==='assistant'?'AXEL / VELOCITY MOTORS':'YOU'));item.append(node('div','',text));$('conversation').append(item);$('conversation').scrollTop=$('conversation').scrollHeight;}
  function render(result) {
    session=result;const s=result.state;
    const selected=config.scenarios.find(x=>x.slug===result.scenario);
    $('scenarioTitle').textContent=selected?.title||'Your next drive';$('afterHours').hidden=result.scenario!=='after-hours';
    if($('scenarioSelect'))$('scenarioSelect').value=result.scenario;
    if(result.transcript.length){$('conversation').replaceChildren();result.transcript.forEach(m=>appendMessage(m.role,m.content));$('suggestions').hidden=true;activate();}
    document.querySelectorAll('.assessmentLink').forEach(a=>a.href=result.assessment_url);
    $('openCRM').href=config.crmUrl+'?session='+encodeURIComponent(result.id);
    notifyNative();
    if(s.cards?.length||s.stage==='discovery')renderVehicles(s.cards||[],s.comparison);
    renderAppointments(s);
    renderFinance(result);
    renderService(result);
    if($('repState'))$('repState').textContent=`${s.customer?.name||'Demo Customer'} · ${(s.stage||'ready').replaceAll('_',' ')} · ${result.turns} conversation turns`;
    if(!result.transcript.length&&result.scenario!=='vehicle-shopping'){
      $('suggestions').replaceChildren();const starter=node('button','',selected?.starter||'Start the conversation');starter.dataset.message=selected?.starter||'Hello';$('suggestions').append(starter);$('suggestions').hidden=false;
    }
  }
  function renderVehicles(vehicles,comparison=false) {
    const box=$('vehicleCards');box.replaceChildren();compared.clear();
    $('inventoryTitle').textContent=comparison?'Side by side.':'Options for your next chapter.';
    $('inventoryNote').textContent=vehicles.length?`${vehicles.length} ${comparison?'vehicles compared':'demo vehicles shown'} · Ask Axel to refine these.`:'No matching vehicles. Try a different budget or preference.';
    for(const v of vehicles){
      const card=node('article','ex-vehicle'),imageBox=node('div','ex-vehicle-image'),image=node('img');image.src='/static/'+v.image.replace(/\.png$/,'.jpg');image.alt='Generated representative '+v.body_style+'; not the exact vehicle';image.loading='lazy';image.onerror=()=>image.remove();imageBox.append(image,node('small','','REPRESENTATIVE IMAGE'));
      const info=node('div','ex-vehicle-info');info.append(node('span','ex-eyebrow',`${v.condition} · ${v.status}`),node('h3','',`${v.year} ${v.make} ${v.model} ${v.trim}`),node('strong','',money(v.display_price??v.special_price??v.price)),node('p','',`${v.mileage.toLocaleString()} mi · ${v.drivetrain} · ${v.seating} seats`),node('p','',v.features.slice(-2).join(' · ')));
      const ask=node('button','ex-button',`Ask about ${v.model} ↗`);ask.onclick=()=>send(`Tell me about ${v.year} ${v.make} ${v.model}, stock ${v.stock}.`);info.append(ask);
      const label=node('label'),check=node('input');check.type='checkbox';check.setAttribute('aria-label','Compare '+v.stock);check.onchange=()=>{if(check.checked&&compared.size>=3){check.checked=false;notice('Choose up to three vehicles to compare.');return;}check.checked?compared.add(v.stock):compared.delete(v.stock);let button=$('compareSelected');if(!button){button=node('button','ex-button','Compare selected');button.id='compareSelected';button.onclick=()=>send('Compare these vehicles: '+[...compared].join(', '));box.after(button);}button.disabled=compared.size<2;};label.append(check,document.createTextNode('Compare'));info.append(label);card.append(imageBox,info);box.append(card);
    }
    $('compareSelected')?.remove();
    if(comparison&&vehicles.length){const wrap=node('div','ex-comparison'),table=node('table'),head=node('tr');head.append(node('th','','Detail'));vehicles.forEach(v=>head.append(node('th','',`${v.make} ${v.model}`)));table.append(head);for(const key of ['stock','condition','drivetrain','seating','fuel_type','mileage','efficiency']){const row=node('tr');row.append(node('th','',key.replaceAll('_',' ')));vehicles.forEach(v=>row.append(node('td','',String(v[key]))));table.append(row);}wrap.append(table);box.append(wrap);}
  }
  function renderAppointments(s){
    $('appointmentSlots').replaceChildren();for(const slot of s.slots||[]){const button=node('button','',slot.label);button.onclick=()=>send(`I'd like the offered ${slot.department} slot ${slot.label} (demo slot ${slot.id}).`);$('appointmentSlots').append(button);}
    $('appointments').replaceChildren();Object.values(s.appointments||{}).forEach(a=>{const card=node('div','ex-appointment');card.append(node('span','ex-eyebrow','DEMO APPOINTMENT · '+(a.status||'confirmed').toUpperCase()),node('strong','',a.label),node('div','',a.vehicle?`${a.vehicle.year} ${a.vehicle.make} ${a.vehicle.model}`:`${a.vehicle_description} · ${a.request}`),node('small','',`${a.confirmation} · No real booking`));$('appointments').append(card);});
  }
  async function send(text,requestId=null,messageMode=mode){
    text=(text||'').trim();if(!text||busy)return;
    activate();stopVoice();busy=true;setState('THINKING','Working on your request · microphone paused');$('thinking').hidden=false;$('sendMessage').disabled=true;$('retryMessage').hidden=true;notice();
    const current=epoch,id=requestId||crypto.randomUUID();failed={text,id,mode:messageMode};
    try{await boot();if(current!==epoch)return;if(!$('conversation').querySelector('.ex-message'))$('conversation').replaceChildren();appendMessage('user',text,'pending');$('messageInput').value='';
      const result=await api(config.turnUrl,{session:session.id,message:text,request_id:id,mode:messageMode});if(current!==epoch)return;render(result);failed=null;
    }catch(e){if(current===epoch){$('conversation').querySelector('.pending')?.remove();notice(e.message);$('retryMessage').hidden=false;$('messageInput').value=text;}}
    finally{if(current===epoch){busy=false;$('thinking').hidden=true;$('sendMessage').disabled=false;setState('READY','Your turn');}}
    if(current===epoch&&!failed&&mode==='voice'&&!nativeSuspended&&!document.hidden)await speakReply(current);
  }
  async function speakReply(current=epoch){
    if(!session?.turns||nativeSuspended||document.hidden)return;
    const cycle=++voiceCycle;
    try{setState('THINKING','Preparing Axel’s spoken reply…');const response=await api(config.speechUrl,{session:session.id,turn:session.turns},{audio:true,timeout:25000});if(current!==epoch||mode!=='voice'||cycle!==voiceCycle)return;const finished=await voice.play(response);if(current!==epoch||cycle!==voiceCycle)return;
      setState('READY','Your turn');$('playReply').hidden=finished;
      if(!finished)notice('Your browser paused audio. Tap Play reply, or continue by typing.');
      else if(mode==='voice'&&!$('messageInput').value.trim()&&!document.hidden&&!document.querySelector('dialog[open]'))setTimeout(()=>{if(current===epoch&&cycle===voiceCycle&&mode==='voice'&&!busy&&!$('messageInput').value.trim()&&!document.hidden&&!document.querySelector('dialog[open]'))listen();},700);
    }catch(e){if(current===epoch&&cycle===voiceCycle){setState('READY','Audio unavailable — text is ready');$('playReply').hidden=false;notice(e.message);}}
  }
  async function transcribe(blob){
    if(busy)return;const current=epoch;busy=true;setState('THINKING','Listening to your message…');$('sendMessage').disabled=true;
    try{await boot();const result=await api(config.voiceUrl+'?session='+encodeURIComponent(session.id),blob,{raw:true,mime:blob.type,timeout:25000});if(current!==epoch)return;busy=false;if(result.text.trim())await send(result.text,null,'voice');else notice('We did not catch that. Tap the microphone and try again.');}
    catch(e){if(current===epoch)notice(e.message);}
    finally{if(current===epoch){busy=false;$('sendMessage').disabled=false;if(state==='THINKING')setState('READY','Tap to speak again, or type.');}}
  }
  function chooseMode(next){mode=next;stopVoice();$('voiceMode').setAttribute('aria-pressed',String(next==='voice'));$('textMode').setAttribute('aria-pressed',String(next==='text'));$('voiceControls').hidden=next!=='voice';setState(busy?'THINKING':'READY',next==='voice'?'Tap the microphone to speak.':'Type at your pace.');}
  async function start(next){activate();chooseMode(next);try{if(next==='voice')await voice.unlock();await boot();if(!config.ready){notice("Live conversation isn't connected in this preview. Explore the inventory, or try the connected site.");return;}if(busy){setState('THINKING','Finishing your request · microphone paused');return;}if(next==='voice'&&mode==='voice')await listen();else $('messageInput').focus();}catch(e){notice(e.message);}}
  $('startVoice').onclick=()=>start('voice');$('startText').onclick=()=>start('text');$('voiceMode').onclick=()=>start('voice');$('textMode').onclick=()=>{chooseMode('text');$('messageInput').focus();};
  $('micButton').onclick=()=>{if(voice.recording)voice.stopCapture(false);else{stopVoice();listen();}};$('interrupt').onclick=()=>{stopVoice();listen();};$('playReply').onclick=()=>speakReply();
  $('messageForm').onsubmit=e=>{e.preventDefault();send($('messageInput').value);};
  $('messageInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send($('messageInput').value);}};
  $('messageInput').oninput=()=>{if(voice.recording){++voiceCycle;voice.stopCapture(true);}if(!busy&&state!=='SPEAKING')setState('READY','Take your time typing · microphone paused');};
  $('suggestions').onclick=e=>{if(e.target.dataset.message)send(e.target.dataset.message);};$('retryMessage').onclick=()=>{if(failed)send(failed.text,failed.id,failed.mode);};
  async function inventory(){try{await boot();const result=await action('inventory',{filters:{status:'available',sort:'price'}});renderVehicles(result.vehicles);}catch(e){notice(e.message);}}
  $('browseInventory').onclick=inventory;$('inventoryStarter').onclick=inventory;
  function showDialog(id){stopVoice();setState(busy?'THINKING':'READY','Microphone paused');document.querySelectorAll('dialog[open]').forEach(d=>{if(d.id!==id)d.close();});if(!$(id).open)$(id).showModal();}
  document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
  function fields(parent,items){const dl=node('dl');for(const[label,value]of items){dl.append(node('dt','',label),node('dd','',value||'Not discussed yet'));}parent.append(dl);}
  $('showHandoff').onclick=async()=>{try{await boot();const h=await action('handoff'),box=$('handoffContent');box.replaceChildren();const grid=node('div','ex-handoff-grid'),customer=node('section','ex-handoff-card'),details=node('section','ex-handoff-card');customer.append(node('span','ex-eyebrow','CUSTOMER PROFILE'),node('h3','',h.customer.name||'Demo Customer'));fields(customer,[['Phone',h.customer.phone],['Email',h.customer.email],['Purchase plan',financeLabel(h.customer.financing_preference)],['Interest',h.customer.interest],['Budget',h.customer.budget],['Priorities',(h.customer.priorities||[]).join(', ')],['Timeline',h.customer.timeframe],['Temperature',h.temperature.replaceAll('_',' ')]]);details.append(node('span','ex-eyebrow','NEXT STEP'),node('h3','',Object.keys(h.appointments).length?'A visit on the calendar.':'Ready for your team.'));fields(details,[['Trade',Object.entries(h.trade).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ')],['Appointment',Object.values(h.appointments).map(a=>`${a.department}: ${a.label} (${a.confirmation})`).join('\n')],['Follow-up',h.follow_up],['Open questions',h.customer.questions],['Service order',h.service_order?`${h.service_order.id} · ${h.service_order.status_label} · ${h.service_order.vehicle||'Vehicle to confirm'}`:'Not opened'],['Financing application',h.financing_application?`${h.financing_application.id} · ${h.financing_application.status}`:'Not opened']]);grid.append(customer,details);box.append(grid);const summary=node('section','ex-handoff-card');summary.append(node('span','ex-eyebrow','AI CONVERSATION SUMMARY'),node('p','',h.summary||'A summary will appear when Axel has gathered enough information. Nothing has been invented to fill this space.'));box.append(summary);const transcript=node('details','ex-transcript');transcript.append(node('summary','',`View full conversation (${h.transcript.length} messages)`));h.transcript.forEach(m=>{const row=node('div','ex-message');row.append(node('small','',m.role==='assistant'?'AXEL':'CUSTOMER'),node('p','',m.content));transcript.append(row);});box.append(transcript);showDialog('handoffDialog');}catch(e){notice(e.message);}};
  function presentation(on){document.body.classList.toggle('ex-presentation',on);$('presentation').textContent=on?'Exit presentation':'⛶ Presentation';$('presentation').setAttribute('aria-label',on?'Exit presentation mode':'Enter presentation mode');if(on){activate();action('presentation').catch(()=>{});if(navigator.wakeLock)navigator.wakeLock.request('screen').then(lock=>{window.exWakeLock=lock;}).catch(()=>{});}else window.exWakeLock?.release();}
  $('presentation').onclick=()=>presentation(!document.body.classList.contains('ex-presentation'));
  $('resetDemo').onclick=()=>{pendingScenario=config.scenario;showDialog('resetDialog');};
  $('confirmReset').onclick=async()=>{
    $('confirmReset').disabled=true;stopVoice();++epoch;
    try{if(session)await api(config.actionUrl,{session:session.id,action:'reset'});session=null;booting=null;failed=null;busy=false;financeShown=null;compared.clear();try{storage.removeItem(storeKey);}catch{}
      $('conversation').replaceChildren();$('vehicleCards').replaceChildren();$('messageInput').value='';$('appointmentSlots').replaceChildren();$('appointments').replaceChildren();$('retryMessage').hidden=true;$('thinking').hidden=true;$('sendMessage').disabled=false;$('playReply').hidden=true;$('compareSelected')?.remove();
      await boot({fresh:true,scenario:pendingScenario});$('conversation').append(node('div','ex-welcome','A fresh conversation. Speak or type to meet Axel.'));setState('READY','New prospect · microphone off');notice(config.ready?'':"Live conversation isn't connected in this preview.");$('resetDialog').close();
    }catch(e){notice(e.message);}finally{$('confirmReset').disabled=false;}
  };
  if($('demoControls')){$('demoControls').onclick=()=>showDialog('controlsDialog');$('painPoint').onchange=()=>{const s=config.scenarios.find(x=>x.slug===$('painPoint').value);if(s){$('scenarioSelect').value=s.slug;$('recommendedDemo').textContent='Recommended: '+s.label;}};$('changeScenario').onclick=()=>{pendingScenario=$('scenarioSelect').value;$('controlsDialog').close();showDialog('resetDialog');};$('sendFeedback').onclick=async()=>{try{await action('feedback',{category:$('feedbackCategory').value,notes:$('feedbackNotes').value});$('feedbackStatus').textContent='Feedback saved. Thank you.';$('feedbackNotes').value='';}catch(e){$('feedbackStatus').textContent=e.message;}};}

  const financeField=name=>$('financeForm').elements.namedItem('finance-'+name);
  const financeLabel=value=>({dealer_financing:'Dealership financing',own_financing:'Own bank / credit union',cash:'Pay in full',undecided:'Still exploring'}[value]||'Not discussed');
  function financeSample(){
    const sample=config.sampleProfiles[financeField('sample_profile').value],box=$('financeSample');box.replaceChildren();if(!sample)return;
    box.append(node('span','ex-eyebrow','FICTIONAL PROFILE / SAMPLE NUMBERS'));
    fields(box,[['Applicant type',sample.applicant_type],['Employer / company',sample.employer],['Annual income / revenue',money(sample.annual_income)],['Monthly housing / premises',money(sample.monthly_housing)],['Time with employer / in business',sample.employment_months+' months']]);
  }
  function clearFinanceErrors(){
    $('financeError').hidden=true;$('financeError').textContent='';
    $('financeForm').querySelectorAll('.ex-field-error').forEach(el=>el.remove());
    $('financeForm').querySelectorAll('[aria-invalid]').forEach(el=>{el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');});
  }
  function showFinanceForm(){
    const application=session?.state.financing_application;if(!application)return;
    const customer=session.state.customer||{};clearFinanceErrors();
    $('financeForm').hidden=application.status==='submitted';$('financeSuccess').hidden=application.status!=='submitted';
    $('financeCRM').href=config.crmUrl+'?session='+encodeURIComponent(session.id);
    if(application.status==='submitted')$('financeReference').textContent=application.id+' · Demo application received';
    else{
      if(session.finance_options){
        const select=financeField('stock');select.replaceChildren();
        for(const item of [{stock:'',label:'Still choosing a vehicle'},...session.finance_options]){const option=node('option','',item.label);option.value=item.stock;select.append(option);}
      }
      const values={name:customer.name==='Demo Customer'?'':customer.name||'',phone:customer.phone||'',email:customer.email||'',financing_preference:customer.financing_preference||'dealer_financing',stock:application.stock||'',sample_profile:'employed',down_payment:'5000',term_months:'undecided'};
      if(application.vehicle&&!Array.from(financeField('stock').options).some(o=>o.value===application.stock)){
        const v=application.vehicle,option=node('option','',`${v.year} ${v.make} ${v.model} · ${v.stock}`);option.value=v.stock;financeField('stock').append(option);
      }
      for(const[name,value]of Object.entries(values))financeField(name).value=value;
      financeField('demo_acknowledged').checked=false;financeSample();
    }
    showDialog('financeDialog');
    $('financeDialog').scrollTop=0;
    if(application.status==='submitted')$('financeSuccess').focus({preventScroll:true});
  }
  function renderFinance(result){
    const application=result.state.financing_application;
    $('financeStatus').textContent=application?`${application.id} · ${application.status==='submitted'?'Submitted to the fictional finance team':'Draft ready for review'}`:'A fictional application. No credit check.';
    $('openFinance').textContent=application?.status==='submitted'?'View demo application ↗':'Open demo financing application ↗';
    const token=application?.open_request?result.id+':'+application.open_request:null;
    if(token&&token!==financeShown){financeShown=token;showFinanceForm();}
  }
  financeField('sample_profile').onchange=financeSample;
  $('openFinance').onclick=async()=>{
    if(busy){notice('Axel is finishing your request. Please wait a moment.');return;}
    stopVoice();busy=true;$('sendMessage').disabled=true;$('openFinance').disabled=true;setState('THINKING','Opening the demo application · microphone paused');const current=epoch;
    try{await boot();const result=await api(config.financeUrl,{session:session.id,action:'open'});if(current!==epoch)return;render(result);}
    catch(e){if(current===epoch)notice(e.message);}finally{if(current===epoch){busy=false;$('sendMessage').disabled=false;$('openFinance').disabled=false;setState('READY','Application ready · microphone paused');}}
  };
  $('financeForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!session?.state.financing_application)return;
    clearFinanceErrors();stopVoice();busy=true;$('sendMessage').disabled=true;$('submitFinance').disabled=true;$('submitFinance').textContent='Saving your demo application…';
    const current=epoch,fields={};
    for(const name of ['name','phone','email','financing_preference','stock','sample_profile','down_payment','term_months'])fields[name]=financeField(name).value;
    fields.demo_acknowledged=financeField('demo_acknowledged').checked;
    try{const result=await api(config.financeUrl,{session:session.id,action:'submit',application_id:session.state.financing_application.id,fields});if(current!==epoch)return;render(result);showFinanceForm();}
    catch(e){if(current===epoch){$('financeError').textContent=e.message;$('financeError').hidden=false;for(const[name,errors]of Object.entries(e.fields||{})){const input=financeField(name);if(!input)continue;const message=node('small','ex-field-error',errors.map(x=>x.message).join(' '));message.id='finance-error-'+name;input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',message.id);input.after(message);}$('financeForm').querySelector('[aria-invalid]')?.focus();}}
    finally{if(current===epoch){busy=false;$('sendMessage').disabled=false;$('submitFinance').disabled=false;$('submitFinance').textContent='Submit demo application ↗';setState('READY','Application reviewed · microphone paused');}}
  };

  let serviceSeen=null, serviceShown=null, serviceVersion=0, serviceSlotRequest=0;
  const serviceField=name=>$('serviceForm').elements.namedItem('service-'+name);
  function chooseDepartment(department){
    const on=department==='service';$('salesPanel').hidden=on;$('servicePanel').hidden=!on;
    $('salesDepartment').setAttribute('aria-pressed',String(!on));$('serviceDepartment').setAttribute('aria-pressed',String(on));
  }
  $('salesDepartment').onclick=()=>chooseDepartment('sales');
  $('serviceDepartment').onclick=()=>chooseDepartment('service');
  $('startService').onclick=()=>{activate();chooseDepartment('service');$('openService').focus();};
  $('askService').onclick=()=>{activate();chooseMode('text');$('messageInput').value='I would like to arrange service for my vehicle.';$('messageInput').focus();};
  function renderService(result){
    const order=result.service_order, box=$('serviceSummary'),key=order?result.id+':'+order.id:null;
    $('serviceDeskLink').href=config.crmUrl+'?session='+encodeURIComponent(result.id)+'#service';
    $('refreshService').hidden=!order;
    $('openService').textContent=order?.customer_editable?'Review service intake ↗':order?'View service order ↗':'Start service intake ↗';
    if(order){
      box.replaceChildren();box.append(node('span','ex-eyebrow',order.id),node('h3','',order.vehicle||'Vehicle to confirm'),node('span','ex-pill',order.status_label));
      fields(box,[['Requested work',order.service_labels.join(', ')],['Your concern',order.concern],['Mileage',order.mileage==null?'Not provided':String(order.mileage)],['Advisor',order.advisor],['Visit',order.appointment?`${order.appointment.label} · ${order.appointment.status}`:'Not scheduled'],['Visit preference',order.visit_label]]);
      if(order.advisor_notes)box.append(node('p','',order.advisor_notes));
      if(key!==serviceSeen){serviceSeen=key;chooseDepartment('service');activate();}
    }else{
      box.replaceChildren();box.append(node('span','ex-eyebrow','READY WHEN YOU ARE'),node('h3','','A smoother service visit.'),node('p','','Start with your vehicle and what you’ve noticed. Axel prepares the handoff for your service advisor.'));
      if(serviceSeen){serviceSeen=null;chooseDepartment(result.scenario==='service'?'service':'sales');}
      if(result.scenario==='service')chooseDepartment('service');
    }
    const token=result.state.service_open_request?result.id+':'+result.state.service_open_request:null;
    if(token&&token!==serviceShown){serviceShown=token;showServiceForm();}
  }
  function showServiceForm(saved=false){
    const order=session?.service_order,customer=session?.state.customer||{};
    serviceVersion=order?.version||0;++serviceSlotRequest;
    $('serviceError').hidden=true;$('serviceError').textContent='';
    $('serviceForm').querySelectorAll('.ex-field-error').forEach(el=>el.remove());
    $('serviceForm').querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
    const done=saved||(order&&!order.customer_editable);
    $('serviceForm').hidden=!!done;$('serviceSuccess').hidden=!done;
    $('serviceCRM').href=config.crmUrl+'?session='+encodeURIComponent(session.id)+'#service';
    if(done){$('serviceReference').textContent=`${order.id} · ${order.status_label}`;}
    else{
      const values={name:customer.name==='Demo Customer'?'':customer.name||'',phone:customer.phone||'',email:customer.email||'',vehicle:order?.vehicle||'',mileage:order?.mileage??'',concern:order?.concern||'',visit_type:order?.visit_type||'undecided'};
      for(const[name,value]of Object.entries(values))serviceField(name).value=value;
      $('serviceForm').querySelectorAll('[name="service-services"]').forEach(el=>el.checked=(order?.services||[]).includes(el.value));
      serviceField('demo_acknowledged').checked=false;$('serviceDay').value='';
      $('serviceSlot').replaceChildren(new Option('Save intake without a new appointment',''));$('serviceSlot').disabled=false;$('submitService').disabled=false;
      $('serviceSlotHint').textContent='Select a date to see demo intake times.';
      $('serviceExistingVisit').textContent=order?.appointment?`Current intake: ${order.appointment.label}. Leave the time blank to keep it.`:'';
    }
    showDialog('serviceDialog');$('serviceDialog').scrollTop=0;
    if(done)$('serviceSuccess').focus({preventScroll:true});
  }
  async function openService(show=true){
    if(busy){notice('Axel is finishing your request. Please wait a moment.');return;}
    stopVoice();busy=true;$('sendMessage').disabled=true;$('openService').disabled=true;const current=epoch;
    try{await boot();const result=await api(config.serviceUrl,{session:session.id,action:'open'});if(current!==epoch)return;render(result);chooseDepartment('service');if(show)showServiceForm();}
    catch(e){if(current===epoch)notice(e.message);}finally{if(current===epoch){busy=false;$('sendMessage').disabled=false;$('openService').disabled=false;setState('READY','Service workspace · microphone paused');}}
  }
  $('openService').onclick=()=>openService();$('refreshService').onclick=()=>openService(false);
  $('serviceDay').onchange=async()=>{
    const day=$('serviceDay').value,request=++serviceSlotRequest,current=epoch;
    $('serviceSlot').replaceChildren(new Option('Save intake without a new appointment',''));
    if(!day){$('serviceSlotHint').textContent='Select a date to see demo intake times.';$('serviceSlot').disabled=false;$('submitService').disabled=false;return;}
    $('serviceSlot').disabled=true;$('submitService').disabled=true;$('serviceSlotHint').textContent='Finding demo intake times…';
    try{const result=await api(config.serviceUrl,{session:session.id,action:'slots',day});if(request!==serviceSlotRequest||current!==epoch)return;
      for(const slot of result.slots)$('serviceSlot').append(new Option(slot.label,slot.id));
      $('serviceSlotHint').textContent=result.slots.length?'Select a time to confirm it with your intake.':result.reason||'No intake times on this date. Try another day.';
    }catch(e){if(request===serviceSlotRequest&&current===epoch)$('serviceSlotHint').textContent=e.message;}
    finally{if(request===serviceSlotRequest&&current===epoch){$('serviceSlot').disabled=false;$('submitService').disabled=false;}}
  };
  $('serviceForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!session)return;
    stopVoice();busy=true;$('sendMessage').disabled=true;$('submitService').disabled=true;$('serviceError').hidden=true;
    $('serviceForm').querySelectorAll('.ex-field-error').forEach(el=>el.remove());$('serviceForm').querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
    const current=epoch,values={};
    for(const name of ['name','phone','email','vehicle','mileage','concern','visit_type'])values[name]=serviceField(name).value;
    values.services=Array.from($('serviceForm').querySelectorAll('[name="service-services"]:checked'),el=>el.value);
    values.demo_acknowledged=serviceField('demo_acknowledged').checked;
    try{const result=await api(config.serviceUrl,{session:session.id,action:'submit',fields:values,version:serviceVersion,slot_id:$('serviceSlot').value});if(current!==epoch)return;render(result);showServiceForm(true);}
    catch(e){if(current===epoch){$('serviceError').textContent=e.message;$('serviceError').hidden=false;for(const[name,errors]of Object.entries(e.fields||{})){const input=$('serviceForm').querySelector(`[name="service-${name}"]`);if(!input)continue;input.setAttribute('aria-invalid','true');input.after(node('small','ex-field-error',errors.map(x=>x.message).join(' ')));}$('serviceError').scrollIntoView({block:'nearest'});}}
    finally{if(current===epoch){busy=false;$('sendMessage').disabled=false;$('submitService').disabled=false;setState('READY','Service intake · microphone paused');}}
  };

  $('shareDemo').onclick=async()=>{try{const result=await action('share');$('shareURL').value=result.url;$('shareQR').src=config.base+'qr/?session='+encodeURIComponent(session.id);showDialog('shareDialog');}catch(e){notice(e.message);}};
  $('copyLink').onclick=async()=>{try{await navigator.clipboard.writeText($('shareURL').value);$('copyLink').textContent='Copied';}catch{$('shareURL').select();$('copyLink').textContent='Select and copy the link';}};
  document.querySelectorAll('.assessmentLink').forEach(a=>a.addEventListener('click',()=>{if(session)fetch(config.actionUrl,{method:'POST',keepalive:true,headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify({session:session.id,action:'assessment_clicked'})}).catch(()=>{});}));
  window.addEventListener('offline',()=>{stopVoice();setState('READY','Connection interrupted');notice('Connection interrupted — reconnecting… The live AI needs internet. Your saved conversation stays here.');});
  window.addEventListener('online',()=>notice('Connection restored. Tap Retry or send your next message.'));
  document.addEventListener('visibilitychange',()=>{if(document.hidden){stopVoice();setState('READY','Paused while this page is hidden');}});
  window.addEventListener('pagehide',()=>voice.stop());
  if(config.ipadApp){
    window.addEventListener('guru:command',event=>{
      const command=event.detail;
      if(command==='pause'){nativeSuspended=true;stopVoice();setState(busy?'THINKING':'READY','Microphone paused');return;}
      if(command==='resume'){nativeSuspended=false;return;}
      if(command==='status'){notifyNative();return;}
      if(busy){notice('Axel is finishing your request. Please wait a moment.');return;}
      if(command==='crm'&&session){stopVoice();location.assign($('openCRM').href);}
      if(command==='inventory'){activate();inventory();$('inventoryTitle').scrollIntoView({behavior:'smooth',block:'start'});}
      if(command==='reset')$('resetDemo').click();
      if(command==='controls')$('demoControls')?.click();
    });
  }
  boot().then(()=>{if(new URLSearchParams(location.search).get('presentation')==='1')presentation(true);if(!config.ready)notice("Live conversation isn't connected in this local preview. You can explore the synthetic inventory.");}).catch(e=>notice(e.message));
})();
