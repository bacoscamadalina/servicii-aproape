"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

class FakeElement {
  constructor(value = "") {
    this.value = value;
    this.disabled = false;
    this.textContent = "";
    this.children = [];
    this.listeners = {};
    this.attributes = new Map();
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  replaceChildren(...children) {
    this.children = children;
  }

  get firstElementChild() {
    return this.children[0];
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  focus() {}
}

test("stale county responses cannot replace a newer county or cleared state", async () => {
  const form = {
    dataset: {
      locationsUrl: "/api/localitati/",
      localityChoose: "Alege localitatea",
      localityNone: "Nu există localități",
      localityCountyFirst: "Alege întâi județul",
      localityLoading: "Se încarcă localitățile…",
      localityLoadError: "Localitățile nu au putut fi încărcate",
      localityRetry: "Reîncearcă selectarea județului.",
      localityCountOne: "{count} localitate disponibilă",
      localityCountMany: "{count} localități disponibile",
    },
  };
  const county = new FakeElement();
  const locality = new FakeElement();
  const status = new FakeElement();
  const elements = {
    "[data-locations-url]": form,
    "#id_county": county,
    "#id_locality": locality,
    "#location-status": status,
  };
  const pendingResponses = new Map();

  global.document = { querySelector: (selector) => elements[selector] };
  global.window = { location: { origin: "http://testserver" } };
  global.Option = function Option(label, value, _defaultSelected, selected) {
    return { label, textContent: label, value, selected };
  };
  global.fetch = (url) => new Promise((resolve) => {
    pendingResponses.set(new URL(url).searchParams.get("county"), resolve);
  });

  delete require.cache[require.resolve("../services/static/services/locations.js")];
  require("../services/static/services/locations.js");

  county.value = "Cluj";
  const clujChange = county.listeners.change();
  county.value = "Iași";
  const iasiChange = county.listeners.change();

  pendingResponses.get("Iași")({
    ok: true,
    json: async () => ({ localities: [{ value: "95079", label: "Iași" }] }),
  });
  await iasiChange;
  pendingResponses.get("Cluj")({
    ok: true,
    json: async () => ({ localities: [{ value: "54984", label: "Cluj-Napoca" }] }),
  });
  await clujChange;

  assert.deepEqual(locality.children.map(({ value }) => value), ["", "95079"]);
  assert.equal(status.textContent, "1 localitate disponibilă");
  assert.equal(locality.attributes.has("aria-busy"), false);

  county.value = "Cluj";
  const clujBeforeClear = county.listeners.change();
  county.value = "";
  await county.listeners.change();

  assert.equal(locality.disabled, true);
  assert.equal(locality.firstElementChild.textContent, "Alege întâi județul");
  assert.equal(locality.attributes.has("aria-busy"), false);

  pendingResponses.get("Cluj")({
    ok: true,
    json: async () => ({ localities: [{ value: "54984", label: "Cluj-Napoca" }] }),
  });
  await clujBeforeClear;

  assert.deepEqual(locality.children.map(({ value }) => value), [""]);
  assert.equal(locality.disabled, true);
  assert.equal(locality.attributes.has("aria-busy"), false);
});
