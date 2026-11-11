(() => {
  "use strict";

  const form = document.querySelector("[data-provider-locations-url]");
  const county = document.querySelector("#id_coverage_county");
  const locality = document.querySelector("#id_coverage_locality");
  const status = document.querySelector("#provider-location-status");
  const retry = document.querySelector("[data-load-provider-localities]");
  if (!form || !county || !locality || !status || !retry) return;

  let requestId = 0;
  let controller = null;
  const copy = {
    choose: form.dataset.localityChoose,
    none: form.dataset.localityNone,
    countyFirst: form.dataset.localityCountyFirst,
    loading: form.dataset.localityLoading,
    loadError: form.dataset.localityLoadError,
    retry: form.dataset.localityRetry,
    countOne: form.dataset.localityCountOne,
    countMany: form.dataset.localityCountMany,
  };

  const replaceOptions = (options, firstLabel) => {
    locality.replaceChildren(
      new Option(firstLabel, ""),
      ...options.map(({ value, label }) => new Option(label, value)),
    );
    locality.disabled = options.length === 0;
  };

  const loadLocalities = async () => {
    const selectedCounty = county.value;
    const currentRequest = ++requestId;
    controller?.abort();
    controller = null;
    status.textContent = "";

    if (!selectedCounty) {
      replaceOptions([], copy.countyFirst);
      locality.removeAttribute("aria-busy");
      return;
    }

    locality.disabled = true;
    locality.setAttribute("aria-busy", "true");
    locality.replaceChildren(new Option(copy.loading, ""));
    controller = new AbortController();
    try {
      const url = new URL(form.dataset.providerLocationsUrl, window.location.origin);
      url.searchParams.set("county", selectedCounty);
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const { localities } = await response.json();
      if (currentRequest !== requestId || county.value !== selectedCounty) return;
      replaceOptions(localities, localities.length ? copy.choose : copy.none);
      status.textContent = (
        localities.length === 1 ? copy.countOne : copy.countMany
      ).replace("{count}", localities.length);
      locality.focus();
    } catch (error) {
      if (error.name === "AbortError" || currentRequest !== requestId) return;
      replaceOptions([], copy.loadError);
      status.textContent = copy.retry;
    } finally {
      if (currentRequest === requestId) {
        locality.removeAttribute("aria-busy");
        controller = null;
      }
    }
  };

  county.addEventListener("change", loadLocalities);
  retry.addEventListener("click", loadLocalities);
})();
