"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

class FakeElement {
  constructor(value = "") {
    this.value = value;
    this.textContent = "";
    this.listeners = {};
    this.attributes = new Map();
  }

  addEventListener(name, listener) { this.listeners[name] = listener; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
}

test("availability ignores stale responses and clears on incomplete scope", async () => {
  const county = new FakeElement("Iași");
  const locality = new FakeElement("95079");
  const category = new FakeElement("constructii");
  const status = new FakeElement();
  const form = {
    dataset: {
      availabilityUrl: "/solicita-oferte/disponibilitate/",
      availabilityIncomplete: "Alege filtrele",
      availabilityLoading: "Verificăm…",
      availabilityZero: "Nicio firmă",
      availabilityOne: "O firmă",
      availabilityMany: "{count} firme",
      availabilityError: "Verificarea a eșuat",
    },
    querySelector: (selector) => ({
      "#id_county": county,
      "#id_locality": locality,
      "#id_category": category,
    })[selector],
  };
  const pending = new Map();
  global.document = { querySelector: (selector) => ({
    ".general-lead-form[data-availability-url]": form,
    "#lead-availability": status,
  })[selector] };
  global.window = { location: { origin: "http://testserver" } };
  global.fetch = (url) => new Promise((resolve) => {
    pending.set(new URL(url).searchParams.get("category"), resolve);
  });

  delete require.cache[require.resolve("../services/static/services/lead_availability.js")];
  require("../services/static/services/lead_availability.js");

  const first = category.listeners.change();
  assert.equal(status.textContent, "Verificăm…");
  category.value = "electricieni";
  const second = category.listeners.change();
  pending.get("electricieni")({ ok: true, json: async () => ({ count: 0 }) });
  await second;
  pending.get("constructii")({ ok: true, json: async () => ({ count: 8 }) });
  await first;
  assert.equal(status.textContent, "Nicio firmă");
  assert.equal(status.attributes.has("aria-busy"), false);

  category.value = "constructii";
  const third = category.listeners.change();
  pending.get("constructii")({ ok: true, json: async () => ({ count: 1 }) });
  await third;
  assert.equal(status.textContent, "O firmă");

  locality.value = "";
  await locality.listeners.change();
  assert.equal(status.textContent, "Alege filtrele");
  assert.equal(status.attributes.has("aria-busy"), false);
});

test("availability reports network errors without blocking the form", async () => {
  const county = new FakeElement("Iași");
  const locality = new FakeElement("95079");
  const category = new FakeElement("constructii");
  const status = new FakeElement();
  const form = {
    dataset: {
      availabilityUrl: "/solicita-oferte/disponibilitate/",
      availabilityLoading: "Verificăm…",
      availabilityError: "Verificarea a eșuat",
    },
    querySelector: (selector) => ({
      "#id_county": county,
      "#id_locality": locality,
      "#id_category": category,
    })[selector],
  };
  global.document = { querySelector: (selector) => ({
    ".general-lead-form[data-availability-url]": form,
    "#lead-availability": status,
  })[selector] };
  global.window = { location: { origin: "http://testserver" } };
  global.fetch = async () => { throw new Error("offline"); };

  delete require.cache[require.resolve("../services/static/services/lead_availability.js")];
  require("../services/static/services/lead_availability.js");
  await category.listeners.change();
  assert.equal(status.textContent, "Verificarea a eșuat");
  assert.equal(status.attributes.has("aria-busy"), false);
});
