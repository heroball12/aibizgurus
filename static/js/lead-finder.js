(() => {
  'use strict';
  const finder = document.querySelector('[data-finder-form]');
  if (finder) {
    const state = finder.querySelector('[data-finder-state]');
    const city = finder.querySelector('[data-finder-city]');
    const button = finder.querySelector('[data-finder-submit]');
    const status = finder.querySelector('[data-finder-status]');
    const retry = finder.querySelector('[data-city-retry]');
    let loading = false, submitting = false, cityRequest = 0, controller;
    state.required = true;
    city.required = true;
    const sync = () => { button.disabled = finder.dataset.searchEnabled !== 'true' || loading || submitting || !state.value || !city.value; };
    async function loadCities() {
      const version = ++cityRequest;
      controller?.abort(); controller = new AbortController();
      const currentController = controller;
      const selectedState = state.value;
      loading = Boolean(selectedState);
      retry.hidden = true;
      city.disabled = true;
      city.replaceChildren(new Option(selectedState ? 'Loading cities…' : 'Choose a state first…', ''));
      sync();
      if (!selectedState) { status.textContent = 'Choose a state, then a city.'; return; }
      status.textContent = 'Loading cities for your state…';
      const timeout = setTimeout(() => currentController.abort(), 10000);
      try {
        const url = new URL(finder.dataset.citiesUrl, location.origin);
        url.searchParams.set('state', selectedState);
        const response = await fetch(url, {credentials:'same-origin', signal:currentController.signal, headers:{Accept:'application/json'}});
        if (response.redirected) throw new Error('Sign in again, then reload this page.');
        if (!response.ok) throw new Error('Cities could not load. Try again.');
        const data = await response.json();
        if (version !== cityRequest) return;
        if (data.state !== selectedState || !Array.isArray(data.cities)) throw new Error('Cities could not load. Try again.');
        city.replaceChildren(new Option('Choose a city…', ''), ...data.cities.map(item => new Option(item.label, item.value)));
        city.disabled = false;
        status.textContent = 'Choose your city. Search covers a 20-mile-wide area; nearby towns may appear.';
      } catch (error) {
        if (version !== cityRequest) return;
        city.replaceChildren(new Option('Cities unavailable — retry below', ''));
        status.textContent = error.name === 'AbortError' ? 'Loading cities timed out. Try again.' : error.message;
        retry.hidden = false;
      } finally {
        clearTimeout(timeout);
        if (version === cityRequest) { loading = false; sync(); }
      }
    }
    state.addEventListener('change', loadCities);
    city.addEventListener('change', () => {
      status.textContent = city.value ? `Search location: ${city.value}, ${state.value}. Nearby towns may appear within the 20-mile-wide area.` : 'Choose a city.';
      sync();
    });
    retry.addEventListener('click', loadCities);
    finder.addEventListener('submit', event => {
      if (button.disabled) { event.preventDefault(); return; }
      submitting = true; sync(); button.textContent = 'Starting search…';
      finder.setAttribute('aria-busy', 'true');
    });
    window.addEventListener('pageshow', () => {
      submitting = false; finder.removeAttribute('aria-busy'); button.textContent = 'Find prospects ↗'; sync();
    });
    sync();
  }

  const batch = document.querySelector('[data-batch-url]');
  if (batch?.dataset.batchOpen !== 'true') return;
  const runForm = batch.querySelector('[data-finder-run]');
  const button = runForm?.querySelector('button');
  const help = batch.querySelector('[data-run-help]');
  let timer, busy = false, stopped = false, failures = 0;
  let canAdvance = batch.dataset.canAdvance === 'true';
  const schedule = delay => { clearTimeout(timer); if (!stopped) timer = setTimeout(tick, delay); };
  async function tick() {
    if (stopped || busy) return;
    if (document.hidden) { schedule(3000); return; }
    busy = true;
    if (button) { button.disabled = true; button.textContent = 'Searching…'; }
    const advancing = Boolean(runForm && canAdvance);
    try {
      const response = await fetch(advancing ? runForm.action : batch.dataset.batchUrl, {
        method: advancing ? 'POST' : 'GET', body: advancing ? new FormData(runForm) : undefined,
        credentials:'same-origin', headers:{Accept:'application/json'}, signal:AbortSignal.timeout(30000),
      });
      if (response.redirected || response.status === 401 || response.status === 403) {
        stopped = true;
        throw new Error('Sign in again, then reopen this search from Search history. Your saved results will be there.');
      }
      const data = await response.json();
      if (!response.ok || !data.batch) throw new Error(data.error || 'The connection paused. Checking your saved search again shortly.');
      failures = 0; canAdvance = data.batch.can_advance;
      batch.querySelector('[data-batch-label]').textContent = data.batch.status_label;
      batch.querySelector('[data-batch-message]').textContent = data.batch.status_message;
      batch.querySelector('progress').value = data.batch.progress_percent;
      batch.querySelector('[data-batch-count]').textContent = `${data.batch.quantity_generated} / ${data.batch.quantity_requested} requested`;
      if (help) help.textContent = 'Progress is saved between steps. Keep this page open, or return to this search to continue.';
      if (!data.batch.is_open) { stopped = true; location.reload(); return; }
    } catch (error) {
      failures++;
      // Read status before another POST: the timed-out request may have saved
      // its checkpoint, or another tab may still own the current lease.
      canAdvance = false;
      batch.querySelector('[data-batch-message]').textContent = ['TimeoutError', 'AbortError'].includes(error.name)
        ? 'The connection paused. Checking saved progress before resuming…' : error.message;
      if (failures >= 5) {
        stopped = true;
        if (help) help.textContent = 'Connection still unavailable. Use Resume search when you reconnect.';
      }
    } finally {
      busy = false;
      if (button && stopped) { button.disabled = false; button.textContent = 'Resume search'; }
      schedule(failures ? Math.min(15000, failures * 3000) : canAdvance && runForm ? 250 : 2500);
    }
  }
  runForm?.addEventListener('submit', event => {
    event.preventDefault(); stopped = false; failures = 0; clearTimeout(timer); tick();
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !stopped) { clearTimeout(timer); tick(); } });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
  tick();
})();
