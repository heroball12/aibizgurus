const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/zoominfo.js', 'utf8');

class Element {
  constructor(values = {}) {Object.assign(this, {dataset:{}, listeners:{}, checked:false, disabled:false, textContent:''}, values);}
  addEventListener(name, callback) {(this.listeners[name] ||= []).push(callback);}
  fire(name, event = {}) {event.preventDefault = () => event.defaultPrevented = true; for(const callback of this.listeners[name] || []) callback(event); return event;}
  hasAttribute(name) {return this.attributes?.includes(name) || false;}
  setAttribute() {}
  removeAttribute() {}
}
function harness(size = 3, manager = false) {
  const boxes = Array.from({length:size}, () => new Element());
  const all = new Element(), count = new Element(), status = new Element();
  const add = new Element({attributes:['data-zi-add'],textContent:'Add to CRM / pipeline',dataset:{busyLabel:'Adding…'}});
  const enrich = new Element({attributes:['data-zi-enrich'],textContent:'Get details'});
  const assignee = manager ? new Element({value:'',selectedOptions:[{textContent:'Choose an agent…'}]}) : null;
  const summary = new Element(), pipelineLink = new Element({dataset:{pipelineUrl:'/crm/pipeline/'}});
  const form = new Element({dataset:{ziSelection:'100',ziEnrichmentLimit:'25'}});
  form.querySelectorAll = key => key === '[data-zi-result]' ? boxes : [add,enrich].filter(button => button.dataset.originalText);
  form.querySelector = key => ({'[data-zi-select-all]':all,'[data-zi-selected-count]':count,'[data-zi-status]':status,'[data-zi-assignee]':assignee,'[data-zi-assignment-summary]':summary,'[data-zi-pipeline-link]':pipelineLink,button:add})[key];
  const listeners = {};
  vm.runInNewContext(source, {
    document:{querySelector:key=>key==='[data-zi-selection]'?form:null,querySelectorAll:()=>[form]},
    window:{addEventListener:(name, callback)=>listeners[name]=callback},
  });
  return {boxes,all,count,status,add,enrich,form,listeners,assignee,summary,pipelineLink};
}
test('select all and individual selection keep the count and mixed state accurate', () => {
  const ui = harness();
  assert.equal(ui.count.textContent,'0 selected · 3 on this page');
  ui.all.checked = true;ui.all.fire('change');
  assert.ok(ui.boxes.every(box=>box.checked));
  assert.equal(ui.count.textContent,'3 selected · 3 on this page');
  ui.boxes[0].checked=false;ui.boxes[0].fire('change');
  assert.equal(ui.all.checked,false);assert.equal(ui.all.indeterminate,true);
  ui.all.checked=false;ui.all.fire('change');
  assert.ok(ui.boxes.every(box=>!box.checked));
});
test('empty selection does not start an import or disable the form', () => {
  const ui=harness();const event=ui.form.fire('submit',{submitter:ui.add});
  assert.equal(event.defaultPrevented,true);
  assert.match(ui.status.textContent,/Select at least one result/);
  assert.equal(ui.add.disabled,false);
  assert.equal(ui.form.dataset.submitting,undefined);
});
test('100 saved results are allowed while paid details retain their separate 25-person limit', () => {
  const ui=harness(100);ui.all.checked=true;ui.all.fire('change');
  const blocked=ui.form.fire('submit',{submitter:ui.enrich});
  assert.equal(blocked.defaultPrevented,true);assert.match(ui.status.textContent,/25 people/);
  const accepted=ui.form.fire('submit',{submitter:ui.add});
  assert.ok(!accepted.defaultPrevented);assert.equal(ui.add.disabled,true);
  assert.match(ui.status.textContent,/Saving selected results/);
  assert.ok(ui.boxes.every(box=>box.checked && !box.disabled));
  assert.equal(ui.form.fire('submit',{submitter:ui.enrich}).defaultPrevented,true);
});
test('browser back restores the add button after submission', () => {
  const ui=harness();ui.boxes[0].checked=true;
  ui.form.fire('submit',{submitter:ui.add});ui.listeners.pageshow();
  assert.equal(ui.add.disabled,false);assert.equal(ui.form.dataset.submitting,undefined);
  assert.equal(ui.add.textContent,'Add to CRM / pipeline');
});
test('owner must select an agent and sees the selected pipeline destination', () => {
  const ui=harness(3,true);ui.boxes[0].checked=true;
  assert.equal(ui.form.fire('submit',{submitter:ui.add}).defaultPrevented,true);
  assert.match(ui.status.textContent,/Choose an agent/);
  assert.equal(ui.add.disabled,false);
  ui.assignee.value='42';ui.assignee.selectedOptions=[{textContent:'Riley Agent (riley)'}];ui.assignee.fire('change');
  assert.match(ui.summary.textContent,/Riley Agent \(riley\)’s pipeline/);
  assert.equal(ui.pipelineLink.href,'/crm/pipeline/?assigned_to=42');
  assert.equal(ui.boxes[0].checked,true);
  assert.ok(!ui.form.fire('submit',{submitter:ui.add}).defaultPrevented);
  assert.match(ui.status.textContent,/Saving selected results to Riley Agent/);
  ui.assignee.value='77';ui.assignee.selectedOptions=[{textContent:'Sam Agent'}];ui.listeners.pageshow();
  assert.match(ui.summary.textContent,/Sam Agent’s pipeline/);
  assert.equal(ui.pipelineLink.href,'/crm/pipeline/?assigned_to=77');
});
