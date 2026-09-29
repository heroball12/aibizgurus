(() => {
  const dialog = document.getElementById('researchDialog');
  if (!dialog) return;
  const report = document.getElementById('researchReport'), status = document.getElementById('researchStatus'), refresh = document.getElementById('researchRefresh');
  let active, busy = false;
  async function scan(force = false) {
    if (!active || busy) return;
    busy = true; refresh.disabled = true; report.setAttribute('aria-busy', 'true');
    status.textContent = 'Checking public pages for business details, chat, booking and online ordering…';
    const payload = new FormData(document.getElementById('researchCSRF'));
    if (force) payload.set('refresh', '1');
    try {
      const response = await fetch(active.dataset.researchUrl, {method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}, body: payload, signal: AbortSignal.timeout(40000)});
      if (response.redirected || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Please refresh and sign in again to research this business.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'The website could not be scanned.');
      // This is our server-rendered, Django-escaped report, never the prospect's raw HTML.
      report.innerHTML = data.html;
      status.textContent = 'Research saved. It follows this business when you add it to the pipeline.';
      active.textContent = 'View website research ↗';
    } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'The scan took too long. Try again shortly or open the website to review it manually.' : error.message; }
    finally { busy = false; refresh.disabled = false; report.removeAttribute('aria-busy'); }
  }
  document.querySelectorAll('[data-research-url]').forEach(button => button.addEventListener('click', () => {
    active = button; report.replaceChildren(); document.getElementById('researchBusiness').textContent = button.dataset.business; dialog.showModal(); scan();
  }));
  refresh.addEventListener('click', () => scan(true));
  function close() { if (!busy) dialog.close(); }
  dialog.querySelectorAll('[data-research-close]').forEach(button => button.addEventListener('click', close));
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
})();

(() => {
  const dialog = document.getElementById('verificationDialog');
  if (!dialog) return;
  const report = document.getElementById('verificationReport'), status = document.getElementById('verificationStatus');
  const run = document.getElementById('verificationRun'), form = document.getElementById('verificationForm');
  let active, busy = false;
  async function load(payload) {
    if (busy || !active) return;
    busy = true; run.disabled = true; form.querySelector('button').disabled = true;
    status.textContent = payload ? (payload.get('action') === 'confirm' ? 'Saving your verification…' : 'Checking the current directory listing and public website. This may take about 30 seconds…') : 'Loading the saved status…';
    try {
      const response = await fetch(active.dataset.verifyUrl, {method: payload ? 'POST' : 'GET', body: payload, credentials: 'same-origin', headers: {Accept: 'application/json'}, signal: AbortSignal.timeout(40000)});
      if (response.redirected || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Please refresh and sign in again.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'The business could not be checked.');
      report.innerHTML = data.html;
      active.closest('.business-verification').querySelector('[data-business-label]').textContent = data.label;
      status.textContent = payload ? 'Check saved. Review the evidence below.' : '';
      if (payload?.get('action') === 'confirm') { form.reset(); form.closest('details').open = false; }
    } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'The check took too long. Reopen this window before trying again; a result may have been saved.' : error.message; }
    finally { busy = false; run.disabled = false; form.querySelector('button').disabled = false; }
  }
  document.querySelectorAll('[data-verify-url]').forEach(button => button.addEventListener('click', () => {
    active = button; form.reset(); report.replaceChildren(); document.getElementById('verificationBusiness').textContent = button.dataset.business; dialog.showModal(); load();
  }));
  run.addEventListener('click', () => { const data = new FormData(form); data.delete('action'); load(data); });
  form.addEventListener('submit', event => { event.preventDefault(); load(new FormData(form)); });
  function close() { if (!busy) dialog.close(); }
  dialog.querySelectorAll('[data-verify-close]').forEach(button => button.addEventListener('click', close));
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
})();
