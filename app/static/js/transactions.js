/* Bulk-select toolbar for the Transactions page.
 *
 * The toolbar (filter + bulk action buttons) is always fully rendered —
 * it never pops in or out. Buttons start `disabled` in the HTML (see
 * transactions/_content.html) and this script only ever toggles that
 * `disabled` attribute based on whether any row is checked; it never
 * shows/hides the toolbar itself.
 *
 * Uses event delegation on `document` rather than binding a listener to
 * each row checkbox — the table (including every checkbox) lives inside
 * #transactions-content, which HTMX replaces wholesale on every filter
 * change, page turn, or bulk action response. Delegation means this
 * script never needs to re-bind anything after a swap; it just keeps
 * listening on an ancestor that's never itself replaced. Button state is
 * reset to disabled/0-selected on every htmx:afterSwap for the same
 * reason a bulk action clears the selection: the checkboxes it was
 * counting no longer exist once the fragment they were part of is gone.
 */
(function () {
  function selectedCheckboxes() {
    return document.querySelectorAll('input[name="transaction_id"]:checked');
  }

  function updateToolbar() {
    const countEl = document.getElementById("bulk-selected-count");
    if (!countEl) return;

    const count = selectedCheckboxes().length;
    countEl.textContent = String(count);

    const disabled = count === 0;
    document.getElementById("bulk-deselect-all").disabled = disabled;
    document.querySelectorAll(".bulk-action-btn").forEach(function (btn) {
      btn.disabled = disabled;
    });
  }

  document.addEventListener("change", function (event) {
    if (event.target.id === "select-all-rows") {
      const checked = event.target.checked;
      document.querySelectorAll('input[name="transaction_id"]').forEach(function (cb) {
        cb.checked = checked;
      });
      updateToolbar();
      return;
    }
    if (event.target.matches && event.target.matches('input[name="transaction_id"]')) {
      updateToolbar();
    }
  });

  document.addEventListener("click", function (event) {
    if (event.target.id !== "bulk-deselect-all") return;
    document.querySelectorAll('input[name="transaction_id"]:checked').forEach(function (cb) {
      cb.checked = false;
    });
    const selectAll = document.getElementById("select-all-rows");
    if (selectAll) selectAll.checked = false;
    updateToolbar();
  });

  document.addEventListener("htmx:afterSwap", updateToolbar);
})();
