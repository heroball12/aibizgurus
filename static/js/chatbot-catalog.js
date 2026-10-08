(() => {
  const input = document.getElementById('chatbotSearch');
  if (!input) return;
  const groups = [...document.querySelectorAll('.catalog-group')];
  const initial = new Map(groups.map(group => [group, group.open]));
  input.addEventListener('input', () => {
    const query = input.value.trim().toLowerCase(); let total = 0;
    for (const group of groups) {
      let count = 0;
      for (const item of group.querySelectorAll('[data-industry]')) {
        const match = item.dataset.industry.toLowerCase().includes(query);
        item.hidden = !match; if (match) count++;
      }
      group.hidden = count === 0;
      group.open = query ? count > 0 : initial.get(group);
      total += count;
    }
    document.getElementById('chatbotResults').textContent = `${total} website chatbot template${total === 1 ? '' : 's'}${query ? (total === 1 ? ' matches your search' : ' match your search') : ''}`;
    document.getElementById('chatbotNoResults').hidden = total > 0;
  });
})();
