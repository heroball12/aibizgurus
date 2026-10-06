const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/lead-finder.js', 'utf8');
class Element {
  constructor(props={}) { Object.assign(this,{value:'',disabled:false,textContent:'',dataset:{},listeners:{},children:[],...props}); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  fire(name) { return this.listeners[name]?.({preventDefault(){}}); }
  querySelector(key) { return this.children[key]; }
  replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; }
  setAttribute() {}
  removeAttribute() {}
}
const response = data => ({ok:true, status:200, redirected:false,json:async()=>data});
const settle = () => new Promise(resolve=>setImmediate(resolve));
function harness({finder, batch, fetch}) {
  const timers = new Map(); let timerID=0, reloads=0;
  const context = {
    document:{hidden:false,querySelector: key=>key==='[data-finder-form]'?finder:batch,addEventListener(){}},
    window:{addEventListener(){}},
    location:{origin:'http://localhost',reload:()=>reloads++},
    Option:class {constructor(label,value){this.label=label;this.value=value;}},
    URL, AbortController, AbortSignal:{timeout:()=>undefined}, FormData:class {}, fetch,
    setTimeout:(fn,delay)=>{timers.set(++timerID,{fn,delay});return timerID;},
    clearTimeout:id=>timers.delete(id),
  };
  vm.runInNewContext(source,context);
  return {timers, reloads:()=>reloads, async next(){const [id,timer]=timers.entries().next().value;timers.delete(id);await timer.fn();await settle();}};
}
function form() {
  const state = new Element(), city = new Element({disabled:true}), button = new Element(), status = new Element(), retry = new Element();
  const finder = new Element({dataset:{searchEnabled:'true',citiesUrl:'/crm/lead-finder/cities/'}});
  finder.children={'[data-finder-state]':state,'[data-finder-city]':city,'[data-finder-submit]':button,'[data-finder-status]':status,'[data-city-retry]':retry};
  return {finder,state,city,button,status,retry};
}
test('changing state clears its city and stale responses cannot replace newer options',async()=>{
  const ui=form(), pending=[];
  harness({finder:ui.finder,fetch:()=>new Promise(resolve=>pending.push(resolve))});
  assert.equal(ui.city.disabled,true); assert.equal(ui.button.disabled,true);
  ui.state.value='FL'; const first=ui.state.fire('change');
  assert.equal(ui.city.value,''); assert.equal(ui.button.disabled,true);
  ui.state.value='CA'; const second=ui.state.fire('change');
  pending[1](response({state:'CA',cities:[{value:'San Diego',label:'San Diego'}]})); await second;
  pending[0](response({state:'FL',cities:[{value:'Miami',label:'Miami'}]})); await first;
  assert.equal(ui.city.options[1].value,'San Diego'); assert.equal(ui.city.disabled,false);
  ui.city.value='San Diego'; ui.city.fire('change'); assert.equal(ui.button.disabled,false);
  ui.state.value=''; await ui.state.fire('change');
  assert.equal(ui.city.disabled,true); assert.equal(ui.city.value,''); assert.equal(ui.button.disabled,true);
});
test('a failed cities request exposes retry and never permits an invalid search',async()=>{
  const ui=form(); let attempts=0;
  harness({finder:ui.finder,fetch:async()=>{if(++attempts===1)throw new Error('offline');return response({state:'FL',cities:[{value:'Miami',label:'Miami'}]});}});
  ui.state.value='FL';await ui.state.fire('change');
  assert.equal(ui.retry.hidden,false);assert.equal(ui.city.disabled,true);assert.equal(ui.button.disabled,true);
  await ui.retry.fire('click');
  assert.equal(ui.city.disabled,false);assert.equal(ui.retry.hidden,true);
});
function batchUI() {
  const button=new Element(), runForm=new Element({action:'/batch/1/run/'});
  runForm.children={button};
  const batch = new Element({dataset:{batchOpen:'true',canAdvance:'true',batchUrl:'/batch/1/status/'}});
  batch.children={'[data-finder-run]':runForm,'[data-run-help]':new Element(),'[data-batch-label]':new Element(),'[data-batch-message]':new Element(),progress:new Element(),'[data-batch-count]':new Element()};
  return batch;
}
const status = (open, advance) => ({batch:{is_open:open,can_advance:advance,status_label:open?'Searching':'Completed',status_message:'test',progress_percent:open?55:100,quantity_generated:open?0:1,quantity_requested:5}});
test('browser continues persisted steps without overlapping requests or duplicate starts',async()=>{
  const calls=[];
  const h=harness({batch:batchUI(),fetch:async(url,options)=>{calls.push(options.method);return response(status(calls.length===1,true));}});
  await settle(); assert.deepEqual(calls,['POST']);
  await h.next(); assert.deepEqual(calls,['POST','POST']);assert.equal(h.reloads(),1);assert.equal(h.timers.size,0);
});
test('after a dropped response, status is checked until the server releases its lease',async()=>{
  const calls=[];let attempt=0;
  const h=harness({batch:batchUI(),fetch:async(url,options)=>{
    calls.push(options.method);attempt++;
    if(attempt===1)throw Object.assign(new Error('timeout'),{name:'TimeoutError'});
    return response(status(attempt!==4, attempt>=3));
  }});
  await settle(); await h.next();await h.next();await h.next();
  assert.deepEqual(calls,['POST','GET','GET','POST']);assert.equal(h.reloads(),1);
});
