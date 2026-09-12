(() => {
  const hero = document.querySelector('[data-arrival]');
  const video = hero?.querySelector('video');
  if (!video) return;
  const controls = hero.querySelector('[data-film-controls]');
  const playButton = hero.querySelector('[data-film-play]');
  const soundButton = hero.querySelector('[data-film-sound]');
  const replayButton = hero.querySelector('[data-film-replay]');
  const fullscreenButton = hero.querySelector('[data-film-fullscreen]');
  const status = hero.querySelector('[data-film-status]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const connection = navigator.connection;
  let userPaused = false;
  let inView = true;
  let sourceLoaded = false;
  let hasError = false;

  // Load only when playback is wanted; data-saving/reduced-motion users get the poster.
  const loadSource = () => {
    if (sourceLoaded) return;
    video.querySelectorAll('source[data-src], track[data-src]').forEach(node => {
      node.src = node.dataset.src;
    });
    sourceLoaded = true;
    video.load();
  };
  const update = () => {
    playButton.textContent = video.paused ? (video.ended ? 'Play again' : 'Play film') : 'Pause';
    playButton.setAttribute('aria-label', video.paused ? 'Play the arrival film' : 'Pause the arrival film');
    soundButton.textContent = video.muted ? 'Sound off' : 'Sound on';
    soundButton.setAttribute('aria-pressed', String(!video.muted));
    soundButton.setAttribute('aria-label', video.muted ? 'Turn film sound on' : 'Mute film sound');
    hero.classList.toggle('is-playing', !video.paused);
  };
  const play = async () => {
    if (hasError) return;
    loadSource();
    try {
      await video.play();
      status.textContent = '';
    } catch (error) {
      // Autoplay may be blocked by the browser; manual play remains available.
      if (error.name !== 'AbortError') status.textContent = 'Select Play film to start.';
    }
    update();
  };
  playButton.addEventListener('click', () => {
    userPaused = !video.paused;
    if (video.paused) play();
    else video.pause();
  });
  soundButton.addEventListener('click', () => {
    video.muted = !video.muted;
    if (!video.muted && video.paused) {
      userPaused = false;
      play();
    }
    update();
  });
  replayButton.addEventListener('click', () => {
    userPaused = false;
    video.currentTime = 0;
    play();
  });
  if (fullscreenButton && (video.requestFullscreen || video.webkitEnterFullscreen)) {
    fullscreenButton.hidden = false;
    fullscreenButton.addEventListener('click', async () => {
      loadSource();
      video.controls = true;
      try {
        if (video.requestFullscreen) await video.requestFullscreen();
        else video.webkitEnterFullscreen();
      } catch (error) {
        video.controls = false;
        status.textContent = 'Full screen is unavailable in this browser.';
      }
    });
    document.addEventListener('fullscreenchange', () => {
      if (!document.fullscreenElement) video.controls = false;
    });
    video.addEventListener('webkitendfullscreen', () => { video.controls = false; });
  }
  video.addEventListener('playing', () => {
    hero.classList.add('has-played');
    update();
  });
  ['pause', 'ended', 'volumechange'].forEach(event => video.addEventListener(event, update));
  const playbackFailed = () => {
    hasError = true;
    controls.hidden = true;
    hero.classList.remove('has-played', 'is-playing');
    status.textContent = 'The film could not load. You can still explore the interactive demo.';
  };
  video.addEventListener('error', playbackFailed);
  video.querySelector('source').addEventListener('error', playbackFailed);
  const autoplayAllowed = () => !reducedMotion.matches && !connection?.saveData && !userPaused;
  const visibilityChanged = () => {
    if (document.hidden || !inView) video.pause();
    else if (autoplayAllowed() && !video.ended) play();
  };
  document.addEventListener('visibilitychange', visibilityChanged);
  reducedMotion.addEventListener('change', () => {
    if (reducedMotion.matches) video.pause();
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(entries => {
      inView = entries[0].isIntersecting;
      visibilityChanged();
    }, { threshold: .15 }).observe(hero);
  }
  // Keep the final desk shot after the first play, with an explicit replay button.
  controls.hidden = false;
  video.muted = true;
  update();
  if (autoplayAllowed() && !document.hidden) play();
})();
