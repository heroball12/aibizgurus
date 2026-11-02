const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

const source = fs.readFileSync('static/js/training.js', 'utf8');
const initialNonce = '11111111-1111-4111-8111-111111111111';
const draftKey = 'academy-quiz:7:3';
const jsonResponse = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const htmlResponse = (status, redirected = false) => ({ok: status < 400, status, redirected, json: async () => {throw new SyntaxError('HTML response');}});
const passed = {score:100, passed:true, feedback:[{question:'What next?',selected:'Listen',correct:'Listen',is_correct:true,explanation:'Ask first.'}]};

class Element {
  constructor() {this.textContent = ''; this.children = []; this.disabled = false; this.listeners = {};}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children = nodes; this.textContent = '';}
  addEventListener(name, callback) {this.listeners[name] = callback;}
}

function harness(fetch, storage = new Map()) {
  const button = new Element(), result = new Element(), quiz = new Element(), calls = [];
  const radios = ['0','1'].map(value => ({name:'q_42', value, checked:value === '0', disabled:false}));
  quiz.dataset = {url:'/training/modules/3/quiz/', nonce:initialNonce, draftKey};
  quiz.querySelector = () => button;
  quiz.querySelectorAll = () => radios;
  quiz.reportValidity = () => radios.some(r => r.checked);
  const document = {
    getElementById: id => ({academyQuiz:quiz, quizResult:result})[id] || null,
    querySelector: () => ({value:'csrf-token'}),
    createElement: () => new Element(),
  };
  vm.runInNewContext(source, {
    document, crypto:{randomUUID}, AbortSignal:{timeout:() => undefined},
    sessionStorage:{getItem:key => storage.get(key) || null, setItem:(key,value) => storage.set(key,value), removeItem:key => storage.delete(key)},
    fetch:async (url,options) => {calls.push({url,...JSON.parse(options.body)}); return fetch(url,options);},
  });
  return {
    quiz, button, result, radios, storage, calls,
    submit:() => quiz.listeners.submit({preventDefault(){}}),
    choose(value) {radios.forEach(r => r.checked = r.value === String(value)); quiz.listeners.change();},
  };
}

test('an HTML server failure is not presented as a session error or grading result', async () => {
  const ui = harness(async () => htmlResponse(500));
  await ui.submit();
  assert.match(ui.result.textContent, /training server could not save/);
  assert.match(ui.result.textContent, /not a grading result/);
  assert.doesNotMatch(ui.result.textContent, /sign-in expired|session or connection/);
  assert.equal(ui.radios[0].checked, true);
  assert.equal(ui.button.disabled, false);
  assert.ok(ui.storage.has(draftKey));
});

test('a login redirect explains expired authentication and retains selected answers', async () => {
  const ui = harness(async () => htmlResponse(200, true));
  ui.choose(1);
  await ui.submit();
  assert.match(ui.result.textContent, /sign-in expired/);
  assert.equal(JSON.parse(ui.storage.get(draftKey)).answers['42'], 1);
});

test('a connection retry resends the same attempt and success clears the draft', async () => {
  let count = 0;
  const ui = harness(async () => {if(++count === 1) throw new TypeError('Failed to fetch'); return jsonResponse(passed);});
  await ui.submit();
  assert.match(ui.result.textContent, /connection was interrupted/);
  await ui.submit();
  assert.equal(ui.calls[0].nonce, ui.calls[1].nonce);
  assert.equal(ui.result.children[0].textContent, '100% — Knowledge check passed');
  assert.equal(ui.storage.has(draftKey), false);
  assert.notEqual(ui.quiz.dataset.nonce, initialNonce);
  assert.equal(ui.radios[0].disabled, false);
});

test('reload restores the draft and retry nonce; changing an answer creates a new attempt', async () => {
  const original = harness(async () => htmlResponse(503));
  original.choose(1);
  await original.submit();
  const restored = harness(async () => jsonResponse(passed), original.storage);
  assert.equal(restored.radios[1].checked, true);
  assert.equal(restored.quiz.dataset.nonce, original.calls[0].nonce);
  assert.match(restored.result.textContent, /restored/);
  restored.choose(0);
  assert.notEqual(restored.quiz.dataset.nonce, original.calls[0].nonce);
  await restored.submit();
  assert.equal(restored.calls[0].answers['42'], 0);
});

test('an attempt limit displays the server wait time without discarding answers', async () => {
  const ui = harness(async () => jsonResponse({error:'Try again in 12 minutes. Other modules remain available.'}, 429));
  await ui.submit();
  assert.match(ui.result.textContent, /12 minutes/);
  assert.match(ui.result.textContent, /answers have been kept/);
  assert.equal(ui.radios[0].checked, true);
});

test('incomplete answers are not submitted, and below-threshold results are clearly graded', async () => {
  const ui = harness(async () => jsonResponse({...passed,score:0,passed:false}));
  ui.radios.forEach(r => r.checked = false);
  await ui.submit();
  assert.equal(ui.calls.length, 0);
  ui.choose(1);
  await ui.submit();
  assert.match(ui.result.children[0].textContent, /^0% — Not passed yet/);
  assert.equal(ui.result.children.length, 2);
});

test('unavailable browser storage does not prevent grading', async () => {
  const blocked = {get(){throw new Error('Storage disabled');}, set(){throw new Error('Storage disabled');}, delete(){throw new Error('Storage disabled');}};
  const ui = harness(async () => jsonResponse(passed), blocked);
  ui.choose(1);
  await ui.submit();
  assert.equal(ui.result.children[0].textContent, '100% — Knowledge check passed');
});
