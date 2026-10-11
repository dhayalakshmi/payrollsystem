/* Page behaviour (kept out of the HTML so a strict Content-Security-Policy can block inline scripts) */
document.addEventListener("click", function (e) {
  if (e.target.closest("[data-print]")) window.print();
});
document.addEventListener("change", function (e) {
  var el = e.target.closest("[data-autosubmit]");
  if (el && el.form) el.form.submit();
});
