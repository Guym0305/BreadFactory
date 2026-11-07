(function () {
  const form = document.querySelector(".order-form");
  if (form) {
    const remaining = Number(form.dataset.remaining || 0);
    const inputs = Array.from(form.querySelectorAll(".qty-input"));
    const total = document.querySelector("[data-total]");
    const count = document.querySelector("[data-count]");
    const message = document.querySelector("#order-message");
    const paymentInputs = Array.from(form.querySelectorAll('input[name="payment_method"]'));
    const otherWrap = form.querySelector("[data-pay-other]");
    const otherInput = form.querySelector('input[name="payment_other"]');

    const valueOf = (input) => {
      const parsed = Number.parseInt(input.value, 10);
      return Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
    };

    const used = () => inputs.reduce((sum, input) => sum + valueOf(input), 0);

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
      if (count) {
        const one = form.dataset.oneLoaf || "1 loaf";
        const many = form.dataset.manyLoaves || "{n} loaves";
        count.textContent = loaves === 1 ? one : many.replaceAll("{n}", String(loaves));
      }
      if (total) {
        total.textContent = `₪${Number.isInteger(amount) ? amount.toFixed(0) : amount.toFixed(2)}`;
      }
    };

    const clamp = (input) => {
      input.value = String(valueOf(input));
      const overflow = used() - remaining;
      if (overflow > 0) {
        input.value = String(Math.max(valueOf(input) - overflow, 0));
      }
      render();
    };

    form.querySelectorAll(".step").forEach((button) => {
      button.addEventListener("click", () => {
        const input = button.parentElement.querySelector(".qty-input");
        const direction = Number(button.dataset.dir);
        if (direction > 0 && used() >= remaining) {
          return;
        }
        const next = valueOf(input) + direction;
        if (next < 0) {
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

    form.addEventListener("submit", (event) => {
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
})();
