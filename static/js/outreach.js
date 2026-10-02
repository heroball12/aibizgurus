(() => {
  const dialog = document.getElementById('outreachDialog');
  if (!dialog) return;
  const form = document.getElementById('outreachForm');
  const fields = document.getElementById('outreachFields');
  const subject = document.getElementById('outreachSubject');
  const body = document.getElementById('outreachBody');
  const consent = document.getElementById('outreachConsent');
  const send = document.getElementById('outreachSend');
  const regenerate = document.getElementById('outreachRegenerate');
  const check = document.getElementById('outreachCheck');
  const status = document.getElementById('outreachStatus');
  const help = document.getElementById('outreachHelp');
  let current = null, channel = 'email', busy = false, generation = 0, changed = false;
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  function announce(text, state = '') { status.textContent = text; status.dataset.state = state; }
  async function api(url, payload) {
    const response = await fetch(url, payload === undefined ? {credentials: 'same-origin', headers: {Accept: 'application/json'}} : {
      method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json'}, body: JSON.stringify(payload)
    });
    if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Your session expired or the server could not respond. Refresh and check the outreach history before sending again.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The request could not be completed.');
    return data;
  }
  function labels() {
    const sms = channel === 'sms';
    document.getElementById('outreachTitle').textContent = sms ? 'Review your text' : 'Review your email';
    document.getElementById('outreachSubjectLabel').hidden = sms;
    document.getElementById('outreachConsentLabel').hidden = !sms;
    subject.required = !sms;
    body.maxLength = sms ? 1200 : 6000;
    send.textContent = 'Confirm & send ' + (sms ? 'text' : 'email');
  }
  function count() { document.getElementById('outreachCount').textContent = `${body.value.length.toLocaleString()} / ${body.maxLength.toLocaleString()} characters${channel === 'sms' ? ' · Longer texts may use multiple billable SMS segments.' : ''}`; }
  function display(data) {
    current = data; channel = data.channel; labels();
    subject.value = data.subject; body.value = data.body; count();
    document.getElementById('outreachFrom').textContent = data.sender;
    document.getElementById('outreachTo').textContent = data.recipient;
    const editable = data.status === 'draft';
    fields.disabled = !editable; send.disabled = !editable; regenerate.disabled = !editable && data.status !== 'failed';
    check.hidden = !['sending', 'unknown'].includes(data.status);
    help.hidden = true;
    if (editable) announce('Draft ready. Review and edit below. Nothing has been sent.');
    else if (data.status === 'sent') {
      changed = true;
      announce(data.error || (data.channel === 'email' ? 'Email accepted by Gmail. You can find it in Sent; replies will arrive in your Gmail inbox.' : `Text accepted by the SMS provider. Delivery status: ${data.delivery_status || 'pending'}.`), data.error ? 'error' : 'sent');
    } else announce(data.error || 'Sending is in progress. Check status shortly; do not create another message.', data.status === 'failed' ? 'error' : data.status);
  }
  async function generate() {
    if (busy) return;
    const ticket = ++generation;
    busy = true; current = null; changed = false; consent.checked = false;
    fields.disabled = true; send.disabled = true; regenerate.disabled = true; check.hidden = true; help.hidden = true;
    subject.value = ''; body.value = ''; document.getElementById('outreachFrom').textContent = 'Checking sender…'; document.getElementById('outreachTo').textContent = 'Checking contact…';
    labels(); announce('Guru is reading the saved notes and preparing a personal follow-up…');
    try { const data = await api(dialog.dataset.draftUrl, {channel}); if (ticket === generation) display(data); }
    catch (error) { if (ticket === generation) { announce(error.message, 'error'); help.hidden = false; regenerate.disabled = false; } }
    finally { if (ticket === generation) busy = false; }
  }
  document.querySelectorAll('[data-outreach]').forEach(button => button.addEventListener('click', () => {
    channel = button.dataset.outreach; dialog.showModal(); generate();
  }));
  document.querySelectorAll('[data-outreach-resume]').forEach(button => button.addEventListener('click', async () => {
    current = {id: button.dataset.outreachResume}; fields.disabled = true; send.disabled = true; regenerate.disabled = true;
    dialog.showModal(); await checkStatus();
  }));
  function close() { if (busy) return; generation++; dialog.close(); if (changed) window.location.reload(); }
  dialog.querySelector('[data-outreach-close]').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  body.addEventListener('input', count);
  regenerate.addEventListener('click', () => { if (current && !window.confirm('Replace this draft and your edits with a fresh AI draft?')) return; generate(); });
  async function checkStatus() {
    if (!current || busy) return;
    busy = true; check.disabled = true;
    try { display(await api(`${dialog.dataset.messageBase}${current.id}/status/`)); }
    catch (error) { announce(error.message, 'unknown'); check.hidden = false; }
    finally { busy = false; check.disabled = false; }
  }
  check.addEventListener('click', checkStatus);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !current || current.status !== 'draft') return;
    if (channel === 'sms' && !consent.checked) { announce('Confirm the prospect agreed to receive texts before sending.', 'error'); consent.focus(); return; }
    busy = true; send.disabled = true; regenerate.disabled = true; fields.disabled = true;
    announce('Submitting the message you reviewed…');
    try { display(await api(`${dialog.dataset.messageBase}${current.id}/send/`, {confirmed: true, sms_consent: consent.checked, subject: subject.value, body: body.value})); }
    catch (error) {
      // A lost HTTP response may hide a completed send. Reconcile the same intent before allowing anything else.
      try { const data = await api(`${dialog.dataset.messageBase}${current.id}/status/`); display(data); if (data.status === 'draft') announce(error.message, 'error'); }
      catch (_) { current.status = 'unknown'; announce('The result could not be confirmed. Use Check sending status before taking any other action.', 'unknown'); check.hidden = false; }
    } finally { busy = false; }
  });
})();
