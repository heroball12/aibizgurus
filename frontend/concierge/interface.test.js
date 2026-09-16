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
