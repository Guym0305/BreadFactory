(function () {
  const form = document.querySelector(".order-form");
  if (form) {
    const remaining = Number(form.dataset.remaining || 0);
    const inputs = Array.from(form.querySelectorAll(".qty-input"));
    const total = document.querySelector("[data-total]");
    const count = document.querySelector("[data-count]");
    const message = document.querySelector("#order-message");

    const valueOf = (input) => {
      const parsed = Number.parseInt(input.value, 10);
      return Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
    };

    const used = () => inputs.reduce((sum, input) => sum + valueOf(input), 0);

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

    form.addEventListener("submit", (event) => {
      if (used() < 1) {
        event.preventDefault();
        message.textContent = form.dataset.chooseLoaf || "Choose at least one loaf.";
      }
    });

    render();
  }

  const pending = document.querySelector("[data-poll-order]");
  if (!pending) {
    return;
  }
  const number = pending.getAttribute("data-poll-order");
  const note = document.querySelector("[data-poll-note]");
  let attempts = 0;

  const watch = async () => {
    attempts += 1;
    try {
      const response = await fetch(`/api/v1/orders/${encodeURIComponent(number)}`);
      if (response.ok) {
        const order = await response.json();
        if (order.status === "PAID" || order.status === "DELIVERED") {
          window.location.reload();
          return;
        }
        if (order.status === "CANCELLED") {
          window.location.href = `/order-failed?order_id=${encodeURIComponent(number)}`;
          return;
        }
      }
    } catch (_error) {
      // Keep the confirmation text and try again.
    }
    if (attempts >= 30) {
      if (note) {
        note.textContent = pending.dataset.waitMessage || "This is taking longer than usual. Refresh this page in a moment.";
      }
      return;
    }
    window.setTimeout(watch, 2000);
  };

  window.setTimeout(watch, 2000);
})();
