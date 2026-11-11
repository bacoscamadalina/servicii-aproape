"use strict";

// The server remains authoritative; this only guards the brief navigation window after a submit.
const leadForm = document.querySelector(".provider-lead-form[data-submit-guard]");
const leadSubmit = leadForm?.querySelector('button[type="submit"]');
const leadSubmitStatus = leadForm?.querySelector("[data-submit-status]");

if (leadSubmit) {
  const idleLabel = leadSubmit.textContent;
  let submitting = false;

  leadForm.addEventListener("submit", (event) => {
    if (submitting) {
      event.preventDefault();
      return;
    }
    submitting = true;
    leadForm.setAttribute("aria-busy", "true");
    leadSubmit.disabled = true;
    leadSubmit.textContent = leadSubmit.dataset.submittingLabel;
    if (leadSubmitStatus) leadSubmitStatus.textContent = leadSubmit.dataset.submittingLabel;
  });

  // Browsers can restore the old form from their back/forward cache after navigation.
  window.addEventListener("pageshow", () => {
    submitting = false;
    leadForm.removeAttribute("aria-busy");
    leadSubmit.disabled = false;
    leadSubmit.textContent = idleLabel;
    if (leadSubmitStatus) leadSubmitStatus.textContent = "";
  });
}
