# Vendored libraries

Downloaded once and committed as static files — no CDN, no npm, so the app
renders correctly fully offline (see CLAUDE.md's frontend direction).

| File | Library | Version | Source |
|---|---|---|---|
| `htmx.min.js` | [htmx](https://htmx.org/) | 2.0.10 | `https://unpkg.com/htmx.org@2.0.10/dist/htmx.min.js` |
| `chart.umd.js` | [Chart.js](https://www.chartjs.org/) | 4.5.1 | `https://unpkg.com/chart.js@4.5.1/dist/chart.umd.js` |

To upgrade: re-download from the same unpkg URL pattern with a new version
pin, verify the app still works, update this table.
