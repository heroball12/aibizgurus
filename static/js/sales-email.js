(() => {
  'use strict';
  const root = document.getElementById('emailCopilot');
  if (!root) return;
  const form = document.getElementById('emailOptions');
  const $ = id => document.getElementById(id);
  const history = JSON.parse($('email-history-data').textContent);
  const lengths = JSON.parse($('email-type-lengths').textContent);
  const field = name => form.elements.namedItem(name);
  const key = `sales-email:${root.dataset.user}:${root.dataset.lead}`;
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  let draft = null, dirty = false, generating = false, timer, queue = Promise.resolve();
  const report = message => { $('emailError').textContent = message; $('emailError').hidden = !message; };
  const status = message => { $('emailStatus').textContent = message; };
  function selections() {
    return {email_type: field('email_type').value, focus: field('focus').value, services: [...form.querySelectorAll('[name=services]:checked')].map(x => x.value), include_demo: field('include_demo').checked, include_assessment: field('include_assessment').checked, tone: field('tone').value, length: field('length').value, instructions: field('instructions').value};
  }
  function content() { return {subject: $('emailSubject').value, body: $('emailBody').value, signature: $('emailSignature').value}; }
  function persist() {
    try { sessionStorage.setItem(key, JSON.stringify({options: selections(), draftId: draft?.id, revision: draft?.revision, edits: dirty ? content() : null})); } catch (_) { /* Server drafts remain available. */ }
  }
  function focusServices() {
    const specific = field('focus').value === 'services';
    $('emailServices').hidden = !specific;
    form.querySelectorAll('[name=services]').forEach(x => { x.disabled = !specific; if (!specific) x.checked = false; });
  }
  function restoreOptions(options) {
    if (!options) return;
    ['email_type','focus','tone','length','instructions'].forEach(k => { if (typeof options[k] === 'string') field(k).value = options[k]; });
    ['include_demo','include_assessment'].forEach(k => { field(k).checked = !!options[k]; });
    form.querySelectorAll('[name=services]').forEach(x => { x.checked = (options.services || []).includes(x.value); });
    focusServices();
  }
  function ownEditable() { return draft && draft.employee_id === Number(root.dataset.user) && draft.status === 'draft'; }
  function controls() {
    root.querySelectorAll('button').forEach(button => { button.disabled = generating; });
    if (draft) {
      root.querySelectorAll('[data-action],[data-refine],[data-feedback]').forEach(button => { button.disabled = generating || !ownEditable(); });
      ['emailSubject','emailBody','emailSignature'].forEach(id => { $(id).readOnly = !ownEditable(); });
    }
  }
  function updateHistory(value) {
    const i = history.findIndex(x => x.id === value.id);
    if (i >= 0) history[i] = value; else history.unshift(value);
    renderHistory();
  }
  function renderHistory() {
    const box = $('emailHistory'); box.replaceChildren();
    if (!history.length) { const p = document.createElement('p'); p.textContent = 'Your generated drafts and saved versions will appear here.'; box.append(p); }
    history.forEach(m => {
      const row = document.createElement('article'); row.className = 'email-history-row';
      const text = document.createElement('div'), title = document.createElement('strong'), meta = document.createElement('p'), open = document.createElement('button');
      title.textContent = m.subject;
      meta.textContent = `${m.employee} · ${new Date(m.created_at).toLocaleString()} · ${m.status === 'marked_sent' ? 'Manually marked sent' : m.status === 'discarded' ? 'Discarded' : m.saved ? 'Saved draft' : 'Generated draft'}`;
      open.textContent = 'Review'; open.type = 'button';
      open.addEventListener('click', async () => { try { await flush(); show(history.find(x => x.id === m.id)); } catch(e) { report(e.message); } });
      text.append(title,meta); row.append(text,open); box.append(row);
    });
  }
  function show(value) {
    draft = value; dirty = false;
    $('emailEmpty').hidden = true; $('emailResult').hidden = false;
    $('emailSubject').value = value.subject; $('emailBody').value = value.body; $('emailSignature').value = value.signature;
    $('emailFrom').textContent = `${value.options.sender_name || value.employee} ${value.sender}`;
    $('emailTo').textContent = `${value.options.recipient_name || 'Contact'} · ${value.recipient || 'No email address on file'}`;
    restoreOptions(value.options);
    const subjects = $('emailSubjects'); subjects.replaceChildren();
    value.subjects.forEach(subject => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = subject; button.setAttribute('aria-pressed', String(subject === value.subject));
      button.addEventListener('click', () => { if (!ownEditable()) return; $('emailSubject').value = subject; subjects.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed',String(x === button))); edited(); });
      subjects.append(button);
    });
    status(value.status === 'marked_sent' ? 'Marked sent · self-reported' : ownEditable() ? (value.saved ? 'Saved to CRM' : 'Draft preserved in history') : 'Read-only history');
    controls(); persist();
  }
  async function request(url,data) {
    const response = await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(data),signal:AbortSignal.timeout(45000)});
    let payload;
    try { payload = await response.json(); }
    catch (_) {
      const sessionExpired = response.status === 401 || (response.redirected && new URL(response.url).pathname.startsWith('/accounts/login/'));
      throw new Error(sessionExpired
        ? 'Your session has expired. Your edits are preserved in this tab; reload and sign in again.'
        : 'The server couldn’t complete that action. Your edits are preserved in this tab. Please try again.');
    }
    if (!response.ok) {
      if (payload.fields) $('emailFields').textContent = Object.entries(payload.fields).map(([k,v]) => `${k.replaceAll('_',' ')}: ${v.join(' ')}`).join('\n');
      const error = new Error(payload.error || 'We couldn’t complete that action. Try again.');
      error.code = payload.code;
      throw error;
    }
    return payload;
  }
  function act(action, extra = {}) {
    const run = async () => {
      if (!draft) return;
      const before = content();
      const {draft: updated} = await request(root.dataset.actionUrl.replace('00000000-0000-0000-0000-000000000000',draft.id),{action,revision:draft.revision,...before,...extra});
      draft = updated; updateHistory(updated);
      // Do not erase keystrokes entered while an autosave was in flight.
      dirty = JSON.stringify(before) !== JSON.stringify(content());
      persist(); controls(); return updated;
    };
    const result = queue.then(run); queue = result.catch(() => {}); return result;
  }
  async function flush() { clearTimeout(timer); await queue; if (dirty && ownEditable()) await act('edit'); }
  function edited() {
    dirty = true; persist(); status('Saving your edits…'); clearTimeout(timer);
    timer = setTimeout(async () => { try { await act('edit'); report(''); status(dirty ? 'Edits pending…' : 'Edits preserved'); } catch(e) { report(e.message); status('Edits preserved in this tab'); } },800);
  }
  ['emailSubject','emailBody','emailSignature'].forEach(id => $(id).addEventListener('input',edited));
  form.addEventListener('change', e => {
    if (e.target.name === 'focus') focusServices();
    if (e.target.name === 'email_type') field('length').value = root.dataset.defaultLength || lengths[field('email_type').value] || 'short';
    persist();
  });
  field('instructions').addEventListener('input',persist);
  async function generate(refine) {
    if (generating) return;
    report(''); $('emailFields').textContent = '';
    try {
      await flush();
      if (refine === 'shorter') field('length').value = 'short';
      if (['direct','friendly','consultative'].includes(refine)) field('tone').value = refine;
      persist(); generating = true; controls(); status('Reading CRM context · writing your email…');
      const data = selections();
      if (draft && draft.employee_id === Number(root.dataset.user)) data.parent = draft.id;
      const result = await request(root.dataset.generateUrl,data);
      status('Finalizing draft…'); updateHistory(result.draft); show(result.draft); $('emailResult').scrollIntoView({behavior:'smooth',block:'start'});
    } catch(e) {
      report(e.name === 'TimeoutError' ? 'Generation took longer than expected. Your options are preserved. Check history after reloading before trying again.' : e.message);
      const needsAdmin = ['ai_configuration','ai_authentication','ai_permission','ai_model_access','ai_quota','ai_request'].includes(e.code);
      status(needsAdmin ? 'Administrator action needed' : e.code === 'ai_daily_limit' ? 'Daily allowance reached' : 'Ready to retry');
    }
    finally { generating = false; controls(); }
  }
  form.addEventListener('submit',e => { e.preventDefault(); generate(); });
  root.querySelectorAll('[data-refine]').forEach(button => button.addEventListener('click',() => generate(button.dataset.refine)));
  root.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click',async () => {
    const action = button.dataset.action;
    if (action === 'sent' && !confirm('Have you sent this email yourself? This records your confirmation in CRM; it does not send or verify delivery.')) return;
    if (action === 'discard' && !confirm('Discard this draft? It will remain in history as discarded.')) return;
    report('');
    try {
      await flush();
      const updated = await act(action);
      if (action.startsWith('copy_')) {
        const email = `${updated.body}\n\n${updated.signature}`;
        const text = action === 'copy_subject' ? updated.subject : action === 'copy_email' ? email : `${updated.subject}\n\n${email}`;
        await navigator.clipboard.writeText(text);
        await act('copied', {copy_part:action});
        status(action === 'copy_all' ? 'Subject + email copied · paste into Gmail' : 'Copied · nothing sent');
      } else { status(action === 'sent' ? 'Marked sent · self-reported' : action === 'save' ? 'Saved to CRM' : 'Draft discarded'); }
    } catch(e) { report(e.name === 'NotAllowedError' ? 'Clipboard access was blocked. Select the subject and body to copy manually.' : e.message); }
  }));
  root.querySelectorAll('[data-feedback]').forEach(button => button.addEventListener('click',async () => { try { await act('feedback',{feedback:button.dataset.feedback,feedback_reason:$('emailFeedbackReason').value}); status('Thanks · feedback recorded'); } catch(e) { report(e.message); } }));
  $('emailStartOver').addEventListener('click',async () => {
    try { await flush(); draft = null; dirty = false; form.reset(); focusServices(); $('emailResult').hidden = true; $('emailEmpty').hidden = false; status('Ready for a new draft'); persist(); report(''); controls(); } catch(e) { report(e.message); }
  });
  window.addEventListener('beforeunload',e => { persist(); if (dirty || generating) { e.preventDefault(); e.returnValue = ''; } });
  renderHistory(); focusServices();
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (stored) {
      restoreOptions(stored.options);
      const previous = history.find(x => x.id === stored.draftId);
      if (previous) {
        show(previous); restoreOptions(stored.options);
        if (stored.edits && ownEditable()) {
          if (stored.revision === previous.revision) { Object.entries(stored.edits).forEach(([k,v]) => { $(`email${k[0].toUpperCase()+k.slice(1)}`).value = v; }); edited(); }
          else { report('A newer server version exists. Your pending edits are shown below for recovery.'); $('emailRecovery').hidden = false; $('emailRecoveredText').value = `${stored.edits.subject}\n\n${stored.edits.body}\n\n${stored.edits.signature}`; }
        }
      }
    }
  } catch (_) { /* Invalid browser cache cannot block the CRM. */ }
})();
