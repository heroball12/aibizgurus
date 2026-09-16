(() => {
  const hero = document.querySelector('[data-arrival]');
  const trigger = hero?.querySelector('[data-meet-guru]');
  const host = document.getElementById('arrivalConcierge');
  if (!trigger || !host || window.parent !== window) return;
  const film = hero.querySelector('video');
  const loading = host.querySelector('.arrival-concierge-loading');
  const launcher = document.querySelector('.concierge-launcher');
  let frame = null, opener = trigger;
  const close = () => {
    frame?.remove(); frame = null;
    host.hidden = true; loading.hidden = false;
    hero.classList.remove('is-guide', 'guide-browsing');
    hero.removeAttribute('aria-label'); hero.setAttribute('aria-labelledby', 'arrival-title');
    hero.querySelectorAll('.arrival-copy,.arrival-bottom,.arrival-topline').forEach(node => { node.inert = false; });
    if (launcher) launcher.hidden = false;
    trigger.setAttribute('aria-expanded', 'false');
    hero.dispatchEvent(new CustomEvent('guruclosed'));
    opener.focus();
  };
  const open = event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); opener = event.currentTarget;
    if (frame) return;
    film?.pause();
    hero.classList.add('is-guide');
    hero.removeAttribute('aria-labelledby'); hero.setAttribute('aria-label', 'Meet Guru, your AI growth guide');
    hero.querySelectorAll('.arrival-copy,.arrival-bottom,.arrival-topline').forEach(node => { node.inert = true; });
    if (launcher) launcher.hidden = true;
    trigger.setAttribute('aria-expanded', 'true'); host.hidden = false;
    frame = document.createElement('iframe');
    frame.title = 'Connect with Guru, your AI growth guide';
    frame.allow = "microphone 'self'; autoplay 'self'";
    frame.src = host.dataset.src;
    host.appendChild(frame);
    hero.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
  };
  trigger.addEventListener('click', open);
  launcher?.addEventListener('click', open);
  host.querySelector('[data-guru-close]').addEventListener('click', close);
  window.addEventListener('message', event => {
    if (!frame || event.origin !== location.origin || event.source !== frame.contentWindow || event.data?.source !== 'aibg-hero-concierge') return;
    if (event.data.type === 'ready') { loading.hidden = true; frame.classList.add('ready'); frame.focus(); }
    if (event.data.type === 'browse') hero.classList.add('guide-browsing');
    if (event.data.type === 'close') close();
  });
})();
