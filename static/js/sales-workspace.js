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
})();
