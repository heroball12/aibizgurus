const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/js/experience.js','utf8');

async function resumeWith(status, code) {
  const elements=new Map(), calls=[], navigations=[];
  const element=id=>{
    if(!elements.has(id))elements.set(id,{value:'',textContent:'',elements:{namedItem:name=>element(name)}});
    return elements.get(id);
  };
  element('experienceConfig').textContent=JSON.stringify({ipadApp:true,ref:'',scenarios:[],base:'/demo/automotive/ipad/',sessionUrl:'/demo/automotive/ipad/session/'});
  const storage={getItem:()=>JSON.stringify({id:'saved-prospect',ref:''}),setItem:()=>assert.fail('Failed resume must not replace the saved ID')};
  const context={
    document:{getElementById:element,querySelector:()=>({value:'csrf'}),querySelectorAll:()=>[],addEventListener(){}},
    window:{addEventListener(){},dispatchEvent(){}},
    location:{assign:url=>navigations.push(url),search:''},
    localStorage:storage,sessionStorage:storage,
    ExperienceVoice:class {stop(){}},
    fetch:async (url,options)=>{calls.push(JSON.parse(options.body));return {ok:false,status:calls.length===1?status:503,json:async()=>({error:'Temporarily unavailable',code})};},
    AbortController,setTimeout,clearTimeout,URLSearchParams,
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve=>setImmediate(resolve));
  return {calls,navigations,notice:element('connectionNotice').textContent};
}

test('a transient resume failure preserves the prospect and never starts another session',async()=>{
  const result=await resumeWith(503,'unavailable');
  assert.equal(result.calls.length,1);
  assert.equal(result.calls[0].resume,'saved-prospect');
  assert.match(result.notice,/Temporarily unavailable/);
});
test('an expired prospect may start a fresh session',async()=>{
  const result=await resumeWith(404,'expired');
  assert.equal(result.calls.length,2);
  assert.equal(result.calls[1].resume,undefined);
});
test('expired employee authentication returns to sign-in without creating a prospect',async()=>{
  const result=await resumeWith(403,'signin_required');
  assert.equal(result.calls.length,1);
  assert.deepEqual(result.navigations,['/demo/automotive/ipad/']);
});
