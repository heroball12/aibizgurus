import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {validPage, followupDraft, isUserCaption} from '../../static/js/concierge-actions.js';

// Exercise the UI controller in an isolated DOM fixture, without paid calls.
function fixture(fetch) {
  const nodes=new Map(), messages=[], listeners={};
  const makeNode=()=>({
    value:"",dataset:{},style:{setProperty(){}},play:async()=>{},pause(){},listeners:{},classList:{values:new Set(),add(x){this.values.add(x);},remove(x){this.values.delete(x);},contains(x){return this.values.has(x);},toggle(){}},
    addEventListener(type,fn){this.listeners[type]=fn;},setAttribute(){},focus(){},replaceChildren(){},scrollIntoView(){},
    contentWindow:{postMessage(message){messages.push(message);}},
  });
  const node=id=>{if(!nodes.has(id))nodes.set(id,makeNode());return nodes.get(id);};
  const pages={home:{path:'/',label:'Home',embedded:true},assessment:{path:'/growth-assessment/',label:'Growth consultation',embedded:true}};
  node('conciergeConfig').textContent=JSON.stringify({available:true,embedded:true,pages,initialPage:'home',startUrl:'/start',maxSeconds:300,callModuleUrl:'/static/call.hash.js'});
  const body=makeNode();body.classList.add('guide-welcome');
  const document={body,getElementById:node,querySelector:selector=>selector==='[name=inputMode]:checked'?{value:'text'}:node(selector),querySelectorAll:()=>[]};
  let connections=0;
  const context=vm.createContext({document,fetch,validPage,followupDraft,isUserCaption,URL,location:{origin:'https://example.test'},innerWidth:1280,
    window:{addEventListener(type,fn){listeners[type]=fn;},matchMedia:()=>({matches:true})},parent:{postMessage(message){messages.push(message);}},crypto:{randomUUID:()=> 'test-id'},
    setInterval:()=>1,clearInterval(){},setTimeout,clearTimeout,confirm:()=>true,
    loadCallModule:async()=>({connectCall:async()=>{connections++;throw new Error('Unexpected connection');}}),
  });
  const source=readFileSync(new URL('../../static/js/concierge.js',import.meta.url),'utf8')
    .replace(/^import .*\n/,'').replace('import(config.callModuleUrl)','loadCallModule()');
  vm.runInContext(source,context);
  return {node,context,body,messages,listeners,connections:()=>connections};
}
const response=data=>({ok:true,json:async()=>data});
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('opening the hero interface does not create a session, and Start still requires consent',async()=>{
  let requests=0;const app=fixture(async()=>{requests++;});
  assert.equal(requests,0);
  await app.node('guideStart').listeners.click();
  assert.equal(requests,0);
  assert.match(app.node('guideStatus').textContent,/agree/);
});

test('navigation reveals the embedded browser without replacing the concierge',()=>{
  const app=fixture();
  vm.runInContext("tool({tool:'navigate_page',args:{page:'assessment'}})",app.context);
  assert.equal(app.body.classList.contains('guide-welcome'),false);
  assert.equal(app.node('guideFrame').src,'https://example.test/growth-assessment/?guided=1');
  assert.equal(app.node('guidePageLabel').textContent,'Growth consultation');
});

test('closing while readiness is pending cancels the session and ignores late credentials',async()=>{
  let resolvePoll;const requests=[];
  const app=fixture(async url=>{
    requests.push(url);
    if(url==='/start')return response({pollUrl:'/poll',stopUrl:'/stop'});
    if(url==='/poll')return new Promise(resolve=>{resolvePoll=resolve;});
    return response({status:'ended'});
  });
  app.node('guideConsentCheck').checked=true;
  const start=app.node('guideStart').listeners.click();await flush();
  await app.node('guideClose').listeners.click();
  assert.ok(requests.includes('/stop'));
  assert.equal(app.messages.at(-1).type,'close');
  resolvePoll(response({status:'ready',credentials:{sessionKey:'test-ephemeral'}}));await start;
  assert.equal(app.connections(),0);
});

test('closing during session creation keeps the interface alive until cancellation',async()=>{
  let resolveStart;const requests=[];
  const app=fixture(async url=>{
    requests.push(url);
    if(url==='/start')return new Promise(resolve=>{resolveStart=resolve;});
    if(url==='/poll')return response({status:'ready',credentials:{}});
    return response({status:'ended'});
  });
  app.node('guideConsentCheck').checked=true;
  const start=app.node('guideStart').listeners.click();await flush();
  const closing=app.node('guideClose').listeners.click();await flush();
  assert.equal(app.messages.some(message=>message.type==='close'),false);
  resolveStart(response({pollUrl:'/poll',stopUrl:'/stop'}));
  await Promise.all([start,closing]);
  assert.ok(requests.includes('/stop'));
  assert.equal(app.messages.at(-1).type,'close');
  assert.equal(app.connections(),0);
});

test('Guru does not navigate while a visitor is composing a message',()=>{
  const app=fixture();app.node('guideText').value='An unfinished question';
  vm.runInContext("tool({tool:'navigate_page',args:{page:'assessment'}})",app.context);
  assert.equal(app.node('guideFrame').src,undefined);
});

test('industry introductions use only configured categories and preserve the guided browser',()=>{
  const app=fixture();
  vm.runInContext("config.pages.demo={path:'/demo/',label:'Demos',embedded:true};config.demoDirectory={'food-hospitality':{name:'Sage'}};tool({tool:'introduce_demo_employee',args:{industry:'food-hospitality'}})",app.context);
  assert.equal(app.node('guideFrame').src,'https://example.test/demo/?industry=food-hospitality&guided=1');
  vm.runInContext("tool({tool:'introduce_demo_employee',args:{industry:'https://evil.test'}})",app.context);
  assert.equal(app.node('guideFrame').src,'https://example.test/demo/?industry=food-hospitality&guided=1');
});

test('scroll gestures can only request bounded up or down movement',()=>{
  const app=fixture();
  vm.runInContext("tool({tool:'scroll_page',args:{direction:'down'}})",app.context);
  assert.equal(app.messages.at(-1).type,'scroll');assert.equal(app.messages.at(-1).direction,'down');
  const count=app.messages.length;
  vm.runInContext("tool({tool:'scroll_page',args:{direction:'anywhere'}})",app.context);
  assert.equal(app.messages.length,count);
});

test('demo handoff closes Guru before permitting another employee connection',async()=>{
  const requests=[];const app=fixture(async url=>{requests.push(url);return response({status:'ended'});});
  vm.runInContext("config.demoDirectory={'food-hospitality':{name:'Sage'}};call={stopUrl:'/stop-guru'};connection={end:async()=>{}}",app.context);
  await app.listeners.message({origin:'https://example.test',source:app.node('guideFrame').contentWindow,data:{source:'aibg-guided-page',type:'demo-handoff',industry:'food-hospitality'}});
  assert.ok(requests.includes('/stop-guru'));
  assert.equal(app.messages.at(-1).type,'demo-handoff-ready');assert.equal(app.messages.at(-1).ok,true);
});

test('a forged handoff from another frame cannot end the active call',async()=>{
  let requests=0;const app=fixture(async()=>{requests++;});
  vm.runInContext("config.demoDirectory={'food-hospitality':{name:'Sage'}};call={stopUrl:'/stop-guru'}",app.context);
  await app.listeners.message({origin:'https://example.test',source:{},data:{source:'aibg-guided-page',type:'demo-handoff',industry:'food-hospitality'}});
  assert.equal(requests,0);assert.equal(app.messages.some(m=>m.type==='demo-handoff-ready'),false);
});

test('a browser media cleanup error still cancels the provider call',async()=>{
  const requests=[];const app=fixture(async url=>{requests.push(url);return response({status:'ended'});});
  vm.runInContext("call={stopUrl:'/stop'};connection={end:async()=>{throw new Error('Audio context closed');}}",app.context);
  await app.node('guideEnd').listeners.click();assert.deepEqual(requests,['/stop']);
});

test('remembering a name saves only tool context, even while an unsent draft exists',async()=>{
  const bodies=[];const app=fixture(async(url,options)=>{bodies.push(JSON.parse(options.body));return response({remembered:true});});
  app.node('guideText').value='private unsent draft';
  vm.runInContext("call={contextUrl:'/context'};tool({tool:'remember_visitor',args:{visitor_name:'Alex',request_summary:'Reservations'}})",app.context);
  await flush();
  assert.deepEqual(bodies,[{visitor_name:'Alex',request_summary:'Reservations'}]);
  assert.equal(app.node('guideFrame').src,undefined);
});

test('warm introduction waits for the spoken goodbye and sends only an opaque token in the URL',async()=>{
  const app=fixture(async()=>response({handoff:'opaque-token',industry:'food-hospitality'}));
  vm.runInContext("config.pages.demo={path:'/demo/',label:'Demos',embedded:true};config.demoDirectory={'food-hospitality':{name:'Sage'}};call={contextUrl:'/context'};let finishSpeech;connection={micEnabled:true,waitForSpeechEnd:()=>new Promise(resolve=>{finishSpeech=resolve;})};tool({tool:'introduce_demo_employee',args:{industry:'food-hospitality',visitor_name:'Alex',request_summary:'Restaurant reservations'}})",app.context);
  await flush();assert.equal(app.node('guideFrame').src,undefined);
  vm.runInContext('finishSpeech(true)',app.context);await flush();
  assert.equal(app.node('guideFrame').src,'https://example.test/demo/?industry=food-hospitality&handoff=opaque-token&guided=1#employeePanel');
  assert.ok(!app.node('guideFrame').src.includes('Alex'));
});

test('a new draft cancels a pending introduction without ending the conversation',async()=>{
  const app=fixture(async()=>response({handoff:'opaque-token',industry:'food-hospitality'}));
  vm.runInContext("config.demoDirectory={'food-hospitality':{name:'Sage'}};call={contextUrl:'/context'};let finishSpeech;connection={waitForSpeechEnd:()=>new Promise(resolve=>{finishSpeech=resolve;})};tool({tool:'introduce_demo_employee',args:{industry:'food-hospitality'}})",app.context);
  await flush();app.node('guideText').value='One more thing';
  vm.runInContext('finishSpeech(true)',app.context);await flush();
  assert.equal(app.node('guideFrame').src,undefined);
  assert.equal(vm.runInContext('!!connection',app.context),true);
});

test('an automatic transfer passes its authorization token without checking the consent box',async()=>{
  let payload;const app=fixture(async(url,options)=>{
    if(url==='/start'){payload=JSON.parse(options.body);return {ok:false,json:async()=>({error:'Test stops before creating a call'})};}
    return response({});
  });
  await vm.runInContext("config.industry='food-hospitality';config.handoff={id:'opaque-token',autoStart:true,mode:'text'};startConversation({handoff:true})",app.context);
  assert.equal(payload.handoff,'opaque-token');assert.equal(payload.consent,false);
  assert.equal(!!app.node('guideConsentCheck').checked,false);
});

test('voice mode shows paused listening honestly and offers intentional interruption',async()=>{
  const app=fixture();
  vm.runInContext("connection={micEnabled:true,listeningState:'assistant-speaking',interrupt:async()=>{connection.listeningState='listening';return true;}};syncMic()",app.context);
  assert.match(app.node('guideListeningLabel').textContent,/Guru is speaking · mic paused/);
  assert.equal(app.node('guideInterrupt').hidden,false);
  await app.node('guideInterrupt').listeners.click();
  assert.match(app.node('guideListeningLabel').textContent,/Your turn/);
  assert.equal(app.node('guideInterrupt').hidden,true);
  vm.runInContext("connection.micEnabled=false;syncMic()",app.context);
  assert.match(app.node('guideListeningLabel').textContent,/microphone off/);
});

test('a draft does not send a typing notification while the microphone is enabled',async()=>{
  let requests=0;const app=fixture(async()=>{requests++;});app.node('guideText').value='Unsent draft';
  await vm.runInContext("config.typingAudioUrl='/typing.mp3';connection={micEnabled:true};notifyTyping()",app.context);
  assert.equal(requests,0);
});

test('failed audio delivery preserves the typed message instead of marking it sent',async()=>{
  const app=fixture(async url=>url==='/text'?response({pollUrl:'/speech',token:'receipt'}):{ok:true,headers:{get:()=> 'audio/mpeg'},arrayBuffer:async()=>new ArrayBuffer(10)});
  app.node('guideText').value='My question';
  vm.runInContext("call={textUrl:'/text'};connection={micEnabled:false,unlockAudio:async()=>{},sendAudio:async()=>false}",app.context);
  await app.node('guideTextForm').listeners.submit({preventDefault(){}});
  assert.equal(app.node('guideText').value,'My question');
  assert.match(app.node('guideStatus').textContent,/could not be sent/);
});
