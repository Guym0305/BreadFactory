(function () {
  const form = document.querySelector(".order-form");
  if (form) {
    const remaining = Number(form.dataset.remaining || 0);
    const inputs = Array.from(form.querySelectorAll(".qty-input"));
    const totals = Array.from(document.querySelectorAll("[data-total]"));
    const counts = Array.from(document.querySelectorAll("[data-count]"));
    const pending = document.querySelector("[data-cart-pending]");
    const message = document.querySelector("#order-message");
    const paymentInputs = Array.from(form.querySelectorAll('input[name="payment_method"]'));
    const otherWrap = form.querySelector("[data-pay-other]");
    const otherInput = form.querySelector('input[name="payment_other"]');

    const valueOf = (input) => {
      const parsed = Number.parseInt(input.value, 10);
      return Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
    };

    const used = () => inputs.reduce((sum, input) => sum + valueOf(input), 0);
    const countsToward = (input) => input.dataset.counts !== "0";
    const counted = () =>
      inputs.reduce((sum, input) => sum + (countsToward(input) ? valueOf(input) : 0), 0);
    const lineMax = (input) => {
      const parsed = Number(input.max);
      return Number.isNaN(parsed) ? 99 : parsed;
    };

    const selectedPayment = () => {
      const chosen = paymentInputs.find((input) => input.checked);
      return chosen ? chosen.value : "";
    };

    const syncPaymentOther = () => {
      if (!otherWrap) {
        return;
      }
      const show = selectedPayment() === "other";
      otherWrap.classList.toggle("is-hidden", !show);
      if (otherInput) {
        otherInput.required = show;
        if (!show) {
          otherInput.value = "";
        }
      }
    };

    const render = () => {
      let amount = 0;
      const loaves = used();
      inputs.forEach((input) => {
        amount += Number(input.dataset.price) * valueOf(input);
      });
      const one = form.dataset.oneLoaf || "1 loaf";
      const many = form.dataset.manyLoaves || "{n} loaves";
      const countText = loaves === 1 ? one : many.replaceAll("{n}", String(loaves));
      const totalText = `₪${Number.isInteger(amount) ? amount.toFixed(0) : amount.toFixed(2)}`;
      counts.forEach((node) => {
        node.textContent = countText;
      });
      totals.forEach((node) => {
        node.textContent = totalText;
      });
      if (pending) {
        const dirty = inputs.some((input) => String(valueOf(input)) !== String(input.dataset.saved ?? input.value));
        pending.hidden = !dirty;
      }
      const recap = document.querySelector("[data-recap-lines]");
      if (recap) {
        recap.replaceChildren();
        inputs.forEach((input) => {
          const qty = valueOf(input);
          if (qty < 1 || !input.dataset.name) {
            return;
          }
          const item = document.createElement("li");
          item.textContent = `${qty} × ${input.dataset.name}`;
          recap.appendChild(item);
        });
      }
      const fulfillment = document.querySelector("[data-fulfillment]");
      if (fulfillment) {
        const pickup = form.querySelector('input[name="fulfillment"][value="pickup"]');
        fulfillment.textContent = pickup && pickup.checked
          ? form.dataset.pickupLabel || "Pickup"
          : form.dataset.deliveryLabel || "Delivery";
      }
    };

    const clamp = (input) => {
      let next = valueOf(input);
      if (countsToward(input)) {
        const overflow = counted() - remaining;
        if (overflow > 0) {
          next -= overflow;
        }
      }
      input.value = String(Math.max(Math.min(next, lineMax(input)), 0));
      render();
    };

    form.querySelectorAll(".step").forEach((button) => {
      button.addEventListener("click", () => {
        const input = button.parentElement.querySelector(".qty-input");
        const direction = Number(button.dataset.dir);
        const next = valueOf(input) + direction;
        if (next < 0 || next > lineMax(input)) {
          return;
        }
        if (direction > 0 && countsToward(input) && counted() >= remaining) {
          return;
        }
        input.value = String(next);
        render();
      });
    });

    inputs.forEach((input) => {
      input.addEventListener("input", () => {
        clamp(input);
      });
    });

    paymentInputs.forEach((input) => {
      input.addEventListener("change", syncPaymentOther);
    });

    form.querySelectorAll('input[name="fulfillment"]').forEach((input) => {
      input.addEventListener("change", render);
    });

    form.addEventListener("submit", (event) => {
      const submitter = event.submitter;
      if (submitter && submitter.dataset.skipValidate === "true") {
        return;
      }
      if (message) {
        message.textContent = "";
      }
      if (used() < 1) {
        event.preventDefault();
        if (message) {
          message.textContent = form.dataset.chooseLoaf || "Choose at least one loaf.";
        }
        return;
      }
      const method = selectedPayment();
      if (!method) {
        event.preventDefault();
        if (message) {
          message.textContent = form.dataset.choosePayment || "Choose how you will pay.";
        }
        return;
      }
      if (method === "other" && !(otherInput && otherInput.value.trim())) {
        event.preventDefault();
        if (message) {
          message.textContent = form.dataset.enterPaymentOther || "Enter how you will pay.";
        }
        if (otherInput) {
          otherInput.focus();
        }
      }
    });

    syncPaymentOther();
    render();
  }

  document.querySelectorAll(".add-cart").forEach((addForm) => {
    const input = addForm.querySelector(".qty-input");
    if (!input) {
      return;
    }
    const max = Number(addForm.dataset.remaining || input.max || 1);
    const valueOf = () => {
      const parsed = Number.parseInt(input.value, 10);
      return Number.isNaN(parsed) || parsed < 1 ? 1 : parsed;
    };
    const clamp = () => {
      const ceiling = Math.max(max, 1);
      input.value = String(Math.min(Math.max(valueOf(), 1), ceiling));
    };
    addForm.querySelectorAll(".step").forEach((button) => {
      button.addEventListener("click", () => {
        const next = valueOf() + Number(button.dataset.dir);
        if (next < 1 || next > max) {
          return;
        }
        input.value = String(next);
      });
    });
    input.addEventListener("input", clamp);
  });

  document.querySelectorAll(".delivery-choice").forEach((choiceForm) => {
    choiceForm.querySelectorAll('input[name="delivery_date"]').forEach((input) => {
      input.addEventListener("change", () => {
        choiceForm.requestSubmit();
      });
    });
  });
})();
