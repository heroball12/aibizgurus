(() => {
  const nav = document.querySelector('.nav');
  const button = nav?.querySelector('.nav-toggle');
  if (!button) return;
  document.documentElement.classList.add('nav-enhanced');
  function toggle(open) {
    nav.classList.toggle('nav-open', open);
    button.setAttribute('aria-expanded', String(open));
    button.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  }
  button.addEventListener('click', () => toggle(button.getAttribute('aria-expanded') !== 'true'));
  nav.addEventListener('keydown', event => { if (event.key === 'Escape' && button.getAttribute('aria-expanded') === 'true') { toggle(false); button.focus(); } });
  nav.querySelector('.navlinks').addEventListener('click', event => { if (event.target.closest('a')) toggle(false); });
  window.matchMedia('(max-width: 760px)').addEventListener('change', () => toggle(false));
})();
