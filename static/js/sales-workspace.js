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
    finder.querySelector('[data-finder-submit]').disabled = false;
    finder.querySelector('[data-finder-submit]').textContent = 'Find prospects ↗';
    finder.removeAttribute('aria-busy');
  });
  const batch = document.querySelector('[data-batch-url]');
  if (batch?.dataset.batchOpen === 'true') {
    let timer, failures = 0, stopped = false;
    async function poll() {
      if (stopped) return;
      if (document.hidden) { timer = setTimeout(poll, 5000); return; }
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch(batch.dataset.batchUrl, {credentials:'same-origin', signal:controller.signal, headers:{Accept:'application/json'}});
        if (!response.ok) throw new Error('Search status unavailable');
        const data = await response.json(); failures = 0;
        if (!data.batch.is_open) { stopped = true; location.reload(); return; }
        batch.querySelector('[data-batch-label]').textContent = data.batch.status_label;
        batch.querySelector('[data-batch-message]').textContent = data.batch.status_message;
        batch.querySelector('progress').value = data.batch.progress_percent;
      } catch (_) {
        failures++;
        batch.querySelector('[data-batch-message]').textContent = 'Connection paused. Checking again shortly; your search can continue in the background.';
      } finally { clearTimeout(timeout); }
      if (!stopped) timer = setTimeout(poll, Math.min(30000, 3000 * (failures + 1)));
    }
    timer = setTimeout(poll, 3000);
    window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  }
})();
