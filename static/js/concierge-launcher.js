(() => {
  const routeKeys = {'/':'home','/solutions/':'solutions','/ai-employees/':'employees','/industries/':'industries','/demo/':'demo','/pricing/':'pricing','/case-studies/':'case_studies','/growth-assessment/':'assessment','/request-consultation/':'custom'};
  const key = routeKeys[location.pathname] || (location.pathname.match(/^\/solutions\/([a-z-]+)\/$/) || [])[1];
  const launcher = document.querySelector('.concierge-launcher');
  if (launcher && key) launcher.href += '?page=' + encodeURIComponent(key);
  if (window.parent === window || new URLSearchParams(location.search).get('guided') !== '1') return;
  document.body.classList.add('guided-page');
  let dirty = false;
  const tell = (type, data = {}) => parent.postMessage({source: 'aibg-guided-page', type, ...data}, location.origin);
  tell('loaded', {path: location.pathname});
  document.addEventListener('input', event => {
    if (event.target.closest('form') && !dirty) { dirty = true; tell('dirty', {dirty: true}); }
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || link.target === '_blank') return;
    if (url.pathname === location.pathname && url.hash) return;
    // Account and other non-guided links retain their destination and query.
    // Opening a separate tab keeps the live call connected here.
    if (!Object.hasOwn(routeKeys,url.pathname) && !/^\/solutions\/[a-z-]+\/$/.test(url.pathname)) {
      link.target = '_blank'; link.rel = 'noopener'; return;
    }
    event.preventDefault();
    tell('navigate', {path: url.pathname, search: url.search, hash: url.hash});
  });
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== parent || event.data?.source !== 'aibg-concierge') return;
    if (event.data.type !== 'focus') return;
    const targets = {top: document.body, content: document.querySelector('main'), calendar: document.querySelector('.calendly-panel'), 'assessment-request': document.getElementById('assessment-request')};
    const target = targets[event.data.section];
    if (!target) return;
    target.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
    target.setAttribute('data-guide-highlight', '');
    setTimeout(() => target.removeAttribute('data-guide-highlight'), 3500);
  });
})();
