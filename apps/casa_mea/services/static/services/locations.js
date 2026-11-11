(() => {
  "use strict";

  const form = document.querySelector("[data-locations-url]");
  const county = document.querySelector("#id_county");
  const locality = document.querySelector("#id_locality");
  const status = document.querySelector("#location-status");

  if (!form || !county || !locality || !status) return;

  let activeRequest = 0;
  let activeController = null;
  const copy = {
    all: form.dataset.localityAll,
    none: form.dataset.localityNone,
    countyFirst: form.dataset.localityCountyFirst,
    loading: form.dataset.localityLoading,
    loadError: form.dataset.localityLoadError,
    retry: form.dataset.localityRetry,
    countOne: form.dataset.localityCountOne,
    countMany: form.dataset.localityCountMany,
  };

  const replaceLocalityOptions = (options, selectedValue = "") => {
    locality.replaceChildren(
      new Option(options.length ? copy.all : copy.none, ""),
      ...options.map(({ value, label }) => new Option(label, value, false, value === selectedValue)),
    );
    locality.disabled = options.length === 0;
  };

  county.addEventListener("change", async () => {
    const selectedCounty = county.value;
    const requestId = ++activeRequest;
    activeController?.abort();
    activeController = null;
    status.textContent = "";

    if (!selectedCounty) {
      replaceLocalityOptions([]);
      locality.firstElementChild.textContent = copy.countyFirst;
      locality.removeAttribute("aria-busy");
      return;
    }

    locality.disabled = true;
    locality.setAttribute("aria-busy", "true");
    locality.replaceChildren(new Option(copy.loading, ""));
    activeController = new AbortController();

    try {
      const url = new URL(form.dataset.locationsUrl, window.location.origin);
      url.searchParams.set("county", selectedCounty);
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: activeController.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const { localities } = await response.json();
      if (requestId !== activeRequest || county.value !== selectedCounty) return;
      replaceLocalityOptions(localities);
      status.textContent = (
        localities.length === 1 ? copy.countOne : copy.countMany
      ).replace("{count}", localities.length);
    } catch (error) {
      if (error.name === "AbortError" || requestId !== activeRequest) return;
      replaceLocalityOptions([]);
      locality.firstElementChild.textContent = copy.loadError;
      status.textContent = copy.retry;
    } finally {
      if (requestId === activeRequest) {
        locality.removeAttribute("aria-busy");
        activeController = null;
      }
    }
  });
})();
