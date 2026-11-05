(() => {
  const selection = document.querySelector('[data-zi-selection]');
  if (selection) {
    const limit = Number(selection.dataset.ziSelection);
    const boxes = [...selection.querySelectorAll('[data-zi-result]')];
    const selectAll = selection.querySelector('[data-zi-select-all]');
    const countLabel = selection.querySelector('[data-zi-selected-count]');
    const update = () => {
      const count = boxes.filter(box => box.checked).length;
      countLabel.textContent = `${count} selected · ${boxes.length} on this page`;
      if(selectAll) {
        selectAll.checked = boxes.length > 0 && count === boxes.length;
        selectAll.indeterminate = count > 0 && count < boxes.length;
        selectAll.disabled = boxes.length === 0;
      }
    };
    boxes.forEach(box => box.addEventListener('change', update));
    selectAll?.addEventListener('change', () => {
      boxes.forEach((box, index) => {box.checked = selectAll.checked && index < limit;});
      update();
    });
    selection.addEventListener('submit', event => {
      const count = boxes.filter(box => box.checked).length;
      const enriching = event.submitter?.hasAttribute('data-zi-enrich');
      const maximum = enriching ? Number(selection.dataset.ziEnrichmentLimit) : limit;
      if (!count || count > maximum) {
        event.preventDefault();
        selection.querySelector('[data-zi-status]').textContent = !count
          ? 'Select at least one result first.'
          : `Choose no more than ${maximum} ${enriching ? 'people for contact details' : 'results'}.`;
      }
    });
    update();
  }
  document.querySelectorAll('[data-zi-submit]').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (form.dataset.submitting) { event.preventDefault(); return; }
      form.dataset.submitting = '1';
      const button = event.submitter || form.querySelector('button');
      if (button) {
        button.dataset.originalText = button.textContent;
        button.textContent = button.dataset.busyLabel || 'Working…';
        button.disabled = true;
      }
      const status = form.querySelector('[data-zi-status]');
      if (status) status.textContent = button?.hasAttribute('data-zi-add')
        ? 'Saving selected results to your CRM…' : 'Waiting for ZoomInfo. Please keep this page open.';
      form.setAttribute('aria-busy', 'true');
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('[data-zi-submit]').forEach(form => {
      delete form.dataset.submitting;
      form.removeAttribute('aria-busy');
      form.querySelectorAll('[data-original-text]').forEach(button => {
        button.textContent = button.dataset.originalText; button.disabled = false;
        delete button.dataset.originalText;
      });
    });
  });
  // Keep the full provider catalog out of the visible list; retain selected topics across filters.
  const filter = document.querySelector('[data-topic-filter]');
  const select = document.querySelector('select[name="topics"]');
  if (filter && select) {
    const catalog = [...select.options].map(option => ({ value: option.value, text: option.textContent }));
    const selected = new Set([...select.selectedOptions].map(option => option.value));
    const label = document.querySelector('[data-topic-count]');
    const draw = () => {
      const query = filter.value.trim().toLocaleLowerCase();
      const matches = catalog.filter(option => option.text.toLocaleLowerCase().includes(query));
      const visible = catalog.filter(option => selected.has(option.value));
      matches.slice(0,100).forEach(option => { if (!selected.has(option.value)) visible.push(option); });
      select.replaceChildren(...visible.map(item => {
        const option = document.createElement('option');
        option.value = item.value; option.textContent = item.text; option.selected = selected.has(item.value);
        return option;
      }));
      label.textContent = `${selected.size}/50 selected · ${matches.length} topics match. Showing up to 100 matches. Use Ctrl/Command to select more than one.`;
    };
    select.addEventListener('change', () => {
      [...select.options].forEach(option => option.selected ? selected.add(option.value) : selected.delete(option.value));
      label.textContent = `${selected.size}/50 selected. Refine the search to find more topics.`;
    });
    let debounce;
    filter.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(draw, 150); });
    draw();
  }
})();
