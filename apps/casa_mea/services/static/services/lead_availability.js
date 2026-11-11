(() => {
  "use strict";

  const form = document.querySelector(".general-lead-form[data-availability-url]");
  const status = document.querySelector("#lead-availability");
  if (!form || !status) return;

  const county = form.querySelector("#id_county");
  const locality = form.querySelector("#id_locality");
  const category = form.querySelector("#id_category");
  if (!county || !locality || !category) return;

  let requestId = 0;
  let controller = null;

  const updateCount = async () => {
    const currentId = ++requestId;
    controller?.abort();
    controller = null;

    if (!county.value || !locality.value || !category.value) {
      status.removeAttribute("aria-busy");
      status.textContent = form.dataset.availabilityIncomplete;
      return;
    }

    status.textContent = form.dataset.availabilityLoading;
    status.setAttribute("aria-busy", "true");
    controller = new AbortController();
    const currentController = controller;
    const url = new URL(form.dataset.availabilityUrl, window.location.origin);
    url.searchParams.set("county", county.value);
    url.searchParams.set("locality", locality.value);
    url.searchParams.set("category", category.value);

    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: currentController.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const { count } = await response.json();
      if (currentId !== requestId) return;
      status.textContent = count === 0
        ? form.dataset.availabilityZero
        : count === 1
          ? form.dataset.availabilityOne
          : form.dataset.availabilityMany.replace("{count}", count);
    } catch (error) {
      if (currentId !== requestId || error.name === "AbortError") return;
      status.textContent = form.dataset.availabilityError;
    } finally {
      if (currentId === requestId) {
        status.removeAttribute("aria-busy");
        controller = null;
      }
    }
  };

  county.addEventListener("change", updateCount);
  locality.addEventListener("change", updateCount);
  category.addEventListener("change", updateCount);
})();
