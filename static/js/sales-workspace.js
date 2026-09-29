(() => {
  'use strict';
  const dialog = document.getElementById('salesGuruDialog');
  const mount = document.getElementById('salesGuruMount');
  const status = document.getElementById('salesGuruStatus');
  let coach = null, ready = false, closing = false, closeTimer;
  function closeCoach() {
    if (closing) return;
    if (!coach || !ready) { coach?.remove(); coach = null; ready = false; dialog.close(); return; }
    closing = true;
    status.textContent = 'Ending the conversation…';
    coach.contentWindow.postMessage({source:'aibg-sales-host', type:'close'}, location.origin);
    closeTimer = setTimeout(() => {
      closing = false;
      status.textContent = 'The conversation is still closing. Use End call in Guru’s window, then close again.';
    }, 12000);
  }
  document.querySelectorAll('[data-sales-guru]').forEach(button => button.addEventListener('click', () => {
    if (!coach) {
      const url = new URL(button.dataset.salesGuru, location.origin);
      if (url.origin !== location.origin || url.pathname !== '/ai/concierge/') return;
      coach = document.createElement('iframe');
      coach.title = 'Guru — private sales coach';
      coach.allow = 'microphone; autoplay';
      coach.src = url.href;
      mount.replaceChildren(coach);
    }
    dialog.showModal();
  }));
  document.querySelector('[data-close-guru]')?.addEventListener('click', closeCoach);
  dialog?.addEventListener('cancel', event => { event.preventDefault(); closeCoach(); });
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== coach?.contentWindow || event.data?.source !== 'aibg-sales-guru') return;
    if (event.data.type === 'ready') ready = true;
    if (['closed','close'].includes(event.data.type)) {
      clearTimeout(closeTimer); closing = false; coach.remove(); coach = null; ready = false; status.textContent = ''; dialog.close();
    }
  });
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const text = document.getElementById(button.dataset.copy)?.textContent;
    if (!text) return;
    const label = button.textContent;
    try { await navigator.clipboard.writeText(text); button.textContent = 'Copied'; }
    catch (_) { button.textContent = 'Select the text above to copy'; }
    setTimeout(() => { button.textContent = label; }, 2500);
  }));
  const industry = document.querySelector('[data-lead-finder-industry]');
  const custom = document.querySelector('.custom-industry-field');
  if (industry && custom) {
    const sync = () => { custom.hidden = industry.value !== 'other'; };
    industry.addEventListener('change', sync); sync();
  }
  const finder = document.querySelector('[data-finder-form]');
  finder?.addEventListener('submit', () => {
    finder.querySelector('[data-finder-submit]').disabled = true;
    finder.querySelector('[data-finder-submit]').textContent = 'Searching…';
    finder.querySelector('[data-finder-status]').textContent = 'Checking public listings and removing duplicates. This can take a few seconds.';
    finder.setAttribute('aria-busy', 'true');
  });
  // Restore a usable form when returning through the browser's page cache.
  window.addEventListener('pageshow', () => {
    if (!finder) return;
    finder.querySelector('[data-finder-submit]').disabled = finder.dataset.searchEnabled !== 'true';
    finder.querySelector('[data-finder-submit]').textContent = 'Find prospects ↗';
    finder.removeAttribute('aria-busy');
  });
  const batch = document.querySelector('[data-batch-url]');
  if (batch?.dataset.batchOpen === 'true') {
    const runForm = batch.querySelector('[data-finder-run]');
    const started = Date.now();
    let timer, failures = 0, stopped = false, running = false;
    function update(data) {
      if (!data.batch) throw new Error('Search status unavailable');
      batch.querySelector('[data-batch-label]').textContent = data.batch.status_label;
      batch.querySelector('[data-batch-message]').textContent = data.batch.status_message;
      batch.querySelector('progress').value = data.batch.progress_percent;
      if (!data.batch.is_open) { stopped = true; clearTimeout(timer); location.reload(); }
    }
    async function runSearch(event) {
      event?.preventDefault();
      if (running) return;
      running = true;
      const button = runForm.querySelector('button');
      button.disabled = true; button.textContent = 'Searching…';
      batch.querySelector('[data-batch-label]').textContent = 'Searching public listings';
      batch.querySelector('[data-batch-message]').textContent = 'Checking real business listings and available contact details…';
      batch.querySelector('[data-run-help]').textContent = 'Usually under a minute. You can see the search status here.';
      try {
        const response = await fetch(runForm.action, {method:'POST', body:new FormData(runForm), credentials:'same-origin', headers:{Accept:'application/json'}, signal:AbortSignal.timeout(90000)});
        if (response.redirected) throw new Error('Your session expired. Sign in again, then reopen this search.');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'The search could not start. Try again.');
        update(data);
      } catch (error) {
        batch.querySelector('[data-run-help]').textContent = error.name === 'TimeoutError' ? 'The connection timed out. Check Search history before retrying; results may still be saved.' : error.message;
        button.disabled = false; button.textContent = 'Check / resume search'; running = false;
      }
    }
    async function poll() {
      if (stopped) return;
      const maxWait = Number(batch.dataset.waitMs) || 180000;
      if (Date.now() - started > maxWait) {
        stopped = true;
        batch.querySelector('[data-batch-label]').textContent = 'Check search status';
        batch.querySelector('[data-batch-message]').textContent = 'This search is taking longer than expected. Reopen it from Search history or use Edit / retry search. Existing results are saved.';
        return;
      }
      if (document.hidden) { timer = setTimeout(poll, 5000); return; }
      try {
        const response = await fetch(batch.dataset.batchUrl, {credentials:'same-origin', signal:AbortSignal.timeout(10000), headers:{Accept:'application/json'}});
        if (!response.ok || response.redirected) throw new Error('Search status unavailable');
        const data = await response.json(); failures = 0; update(data);
      } catch (_) {
        failures++;
        batch.querySelector('[data-batch-message]').textContent = 'Connection paused. Checking again shortly. Reopen Search history if the connection does not recover.';
      }
      if (!stopped) timer = setTimeout(poll, Math.min(30000, 3000 * (failures + 1)));
    }
    if (runForm) { runForm.addEventListener('submit', runSearch); runSearch(); }
    timer = setTimeout(poll, 3000);
    window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  }
})();
