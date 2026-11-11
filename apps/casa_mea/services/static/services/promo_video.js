(() => {
  "use strict";

  const player = document.querySelector("[data-promo-player]");
  if (!player) return;

  const video = player.querySelector("[data-promo-video]");
  const toggle = player.querySelector("[data-promo-toggle]");
  const label = toggle.querySelector("span");
  const progress = player.querySelector("[data-promo-progress]");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  video.controls = false;
  toggle.hidden = false;

  const showPlaybackState = () => {
    const paused = video.paused;
    toggle.classList.toggle("is-paused", paused);
    toggle.setAttribute("aria-label", paused ? toggle.dataset.playLabel : toggle.dataset.pauseLabel);
    label.textContent = paused ? toggle.dataset.playLabel : toggle.dataset.pauseLabel;
  };

  toggle.addEventListener("click", async () => {
    if (video.paused) {
      if (video.ended) video.currentTime = 0;
      try {
        await video.play();
      } catch (_error) {
        video.controls = true;
      }
    } else {
      video.pause();
    }
    showPlaybackState();
  });

  video.addEventListener("play", showPlaybackState);
  video.addEventListener("pause", showPlaybackState);
  video.addEventListener("timeupdate", () => {
    const completion = video.duration ? (video.currentTime / video.duration) * 100 : 0;
    progress.style.transform = `scaleX(${completion / 100})`;
  });

  const observer = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting) video.pause();
  }, { threshold: 0.2 });
  observer.observe(player);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) video.pause();
  });
  reduceMotion.addEventListener("change", () => {
    if (reduceMotion.matches) video.pause();
    showPlaybackState();
  });
  if (reduceMotion.matches) video.pause();
  showPlaybackState();
})();
