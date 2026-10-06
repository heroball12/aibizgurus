(() => {
  const form = document.getElementById('historyRecovery');
  if (!form) return;
  const status = document.getElementById('historyProgress');
  const button = form.querySelector('button');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    const totals = {scanned: 0, recovered: 0, already_counted: 0, unsupported: 0};
    status.textContent = 'Recovering saved history… You can leave this page and resume later.';
    try {
      let done = false;
      while (!done) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 45000);
        let response;
        try {
          response = await fetch(form.action || location.href, {method: 'POST', body: new FormData(form), headers: {'Accept': 'application/json'}, credentials: 'same-origin', signal: controller.signal});
        } finally {
          clearTimeout(timeout);
        }
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Recovery paused. Reload this page to resume from the last saved batch.');
        const data = await response.json();
        form.elements.cursor.value = data.cursor;
        done = data.done;
        for (const key of Object.keys(totals)) totals[key] += data.report[key];
        status.textContent = `${done ? 'Complete.' : 'Working…'} ${totals.scanned} records checked · ${totals.recovered} recovered · ${totals.already_counted} already counted · ${totals.unsupported} without sufficient evidence.`;
      }
      button.textContent = 'History recovered';
    } catch (error) {
      status.textContent = 'Recovery paused. Reload this page to resume safely from the last saved batch.';
      button.disabled = false;
    }
  });
})();
