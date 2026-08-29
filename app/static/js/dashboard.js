/* Renders/re-renders the dashboard's two charts: the "over time" bar
 * chart and the "by category" donut.
 *
 * Chart colors are read from CSS custom properties rather than
 * hardcoded, so both charts follow the same light/dark palette as the
 * rest of the page without duplicating it here. The donut's per-slice
 * colors (--cat-0..--cat-7) are read in the same order the category
 * legend list assigns them server-side (see dashboard/_content.html),
 * so a slice and its legend swatch always match.
 *
 * Both charts have to be (re)built manually on every HTMX swap: HTMX
 * doesn't execute <script> tags injected via a swap, and even if it
 * did, a fresh <canvas> element needs a fresh Chart instance anyway. So
 * this script is loaded once (in dashboard/index.html's head, outside
 * the swapped #dashboard-content region) and listens for htmx:afterSwap.
 */
(function () {
  let barChart = null;
  let categoryChart = null;
  const CATEGORY_COLOR_COUNT = 8;

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function categoryColors() {
    const colors = [];
    for (let i = 0; i < CATEGORY_COLOR_COUNT; i++) {
      colors.push(cssVar("--cat-" + i));
    }
    return colors;
  }

  function renderBarChart() {
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

    if (barChart) {
      barChart.destroy();
      barChart = null;
    }

    barChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: buckets.map((b) => b.label),
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

  function renderCategoryChart() {
    const canvas = document.getElementById("category-chart");
    if (!canvas || typeof Chart === "undefined") {
      return;
    }

    let categories = [];
    try {
      categories = JSON.parse(canvas.dataset.categories || "[]");
    } catch (err) {
      categories = [];
    }

    if (categoryChart) {
      categoryChart.destroy();
      categoryChart = null;
    }

    const colors = categoryColors();
    categoryChart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: categories.map((c) => c.category),
        datasets: [
          {
            data: categories.map((c) => c.total),
            backgroundColor: categories.map((_, i) => colors[i % colors.length]),
            borderColor: cssVar("--bg-elevated"),
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
      },
    });
  }

  function renderCharts() {
    renderBarChart();
    renderCategoryChart();
  }

  document.addEventListener("DOMContentLoaded", renderCharts);
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.target && evt.target.id === "dashboard-content") {
      renderCharts();
    }
  });
})();
