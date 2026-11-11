(() => {
  "use strict";

  const tracker = document.querySelector("[data-provider-engagement-tracker]");
  if (!tracker) return;

  const csrfToken = tracker.querySelector("[name=csrfmiddlewaretoken]")?.value;
  const sent = new Set();
  const record = (eventType) => {
    if (!csrfToken || sent.has(eventType)) return;
    sent.add(eventType);
    const body = new URLSearchParams({ event_type: eventType });
    fetch(tracker.dataset.endpoint, {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-CSRFToken": csrfToken,
      },
      body,
    }).catch(() => sent.delete(eventType));
  };

  record("profile_view");
  document.querySelectorAll("[data-provider-engagement]").forEach((action) => {
    action.addEventListener("click", () => record(action.dataset.providerEngagement));
  });
})();
