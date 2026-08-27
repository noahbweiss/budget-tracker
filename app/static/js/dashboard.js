/* Renders/re-renders the dashboard's over-time chart.
 *
 * Chart colors are read from the CSS custom properties (--income /
 * --expense) rather than hardcoded, so the chart follows the same
 * light/dark palette as the rest of the page without duplicating it here.
 *
 * The chart has to be (re)built manually on every HTMX swap: HTMX doesn't
 * execute <script> tags injected via a swap, and even if it did, a fresh
 * <canvas> element needs a fresh Chart instance anyway. So this script is
 * loaded once (in dashboard/index.html's head, outside the swapped
 * #dashboard-content region) and listens for htmx:afterSwap.
 */
(function () {
  let chart = null;

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function renderChart() {
    const canvas = document.getElementById("dashboard-chart");
    if (!canvas || typeof Chart === "undefined") {
      return;
    }

    let buckets = [];
    try {
      buckets = JSON.parse(canvas.dataset.buckets || "[]");
    } catch (err) {
      buckets = [];
    }

    if (chart) {
      chart.destroy();
      chart = null;
    }

    chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: buckets.map((b) => b.period),
        datasets: [
          {
            label: "Income",
            data: buckets.map((b) => Number(b.income)),
            backgroundColor: cssVar("--income"),
          },
          {
            label: "Spending",
            data: buckets.map((b) => Number(b.spending)),
            backgroundColor: cssVar("--expense"),
          },
        ],
      },
      options: {
        responsive: true,
        scales: { y: { beginAtZero: true } },
      },
    });
  }

  document.addEventListener("DOMContentLoaded", renderChart);
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.target && evt.target.id === "dashboard-content") {
      renderChart();
    }
  });
})();
