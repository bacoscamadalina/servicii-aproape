(() => {
  "use strict";

  document.querySelectorAll(".provider-quote-form").forEach((form) => {
    const total = form.querySelector("[data-quote-total]");
    if (!total) return;
    const fieldset = form.querySelector(".provider-quote-lines");
    const rows = [...form.querySelectorAll(".provider-quote-line")];

    const rowHasContent = (row) => [...row.querySelectorAll("input, select")]
      .some((field) => field.value !== "");
    rows.slice(1).forEach((row) => {
      if (!rowHasContent(row) && !row.querySelector(".provider-error")) row.hidden = true;
    });
    if (fieldset) {
      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.className = "secondary-action provider-quote-add-line";
      addButton.textContent = fieldset.dataset.addLineLabel;
      addButton.addEventListener("click", () => {
        const nextRow = rows.find((row) => row.hidden);
        if (!nextRow) return;
        nextRow.hidden = false;
        nextRow.querySelector("input, select")?.focus();
        if (!rows.some((row) => row.hidden)) addButton.hidden = true;
      });
      if (rows.some((row) => row.hidden)) fieldset.append(addButton);
    }

    const refreshTotal = () => {
      const value = rows.reduce((sum, row) => {
        const quantity = Number.parseFloat(row.querySelector("[data-quote-quantity]")?.value || "0");
        const unitPrice = Number.parseFloat(row.querySelector("[data-quote-unit-price]")?.value || "0");
        return sum + (Number.isFinite(quantity) && Number.isFinite(unitPrice) ? quantity * unitPrice : 0);
      }, 0);
      total.value = value > 0 ? value.toFixed(2) : "";
    };

    form.addEventListener("input", (event) => {
      if (event.target.matches("[data-quote-quantity], [data-quote-unit-price]")) refreshTotal();
    });
    refreshTotal();
  });
})();
