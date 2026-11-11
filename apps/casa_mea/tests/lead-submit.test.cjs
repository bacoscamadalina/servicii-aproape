"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

for (const idleLabel of ["Trimite firmelor eligibile", "Trimite solicitarea"]) {
test(`${idleLabel} submits once and restores its action after back navigation`, () => {
  const formListeners = {};
  const windowListeners = {};
  const attributes = new Map();
  const button = {
    textContent: idleLabel,
    dataset: { submittingLabel: "Se trimite solicitarea…" },
    disabled: false,
  };
  const status = { textContent: "" };
  const form = {
    querySelector: (selector) => selector === "[data-submit-status]" ? status : button,
    addEventListener: (name, listener) => { formListeners[name] = listener; },
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: (name) => attributes.delete(name),
  };
  global.document = { querySelector: (selector) => selector === ".provider-lead-form[data-submit-guard]" ? form : null };
  global.window = { addEventListener: (name, listener) => { windowListeners[name] = listener; } };

  delete require.cache[require.resolve("../services/static/services/lead_submit.js")];
  require("../services/static/services/lead_submit.js");

  let prevented = 0;
  const event = { preventDefault: () => { prevented += 1; } };
  formListeners.submit(event);
  assert.equal(prevented, 0);
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, "Se trimite solicitarea…");
  assert.equal(attributes.get("aria-busy"), "true");
  assert.equal(status.textContent, "Se trimite solicitarea…");

  formListeners.submit(event);
  assert.equal(prevented, 1);

  windowListeners.pageshow();
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, idleLabel);
  assert.equal(attributes.has("aria-busy"), false);
  assert.equal(status.textContent, "");
  formListeners.submit(event);
  assert.equal(prevented, 1);
});
}

test("submit enhancement leaves pages without the form untouched", () => {
  global.document = { querySelector: () => null };
  delete require.cache[require.resolve("../services/static/services/lead_submit.js")];
  assert.doesNotThrow(() => require("../services/static/services/lead_submit.js"));
});
