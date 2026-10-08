'use strict';
for (const form of document.querySelectorAll('[data-office-booking]')) {
  form.addEventListener('submit', () => {
    const button = form.querySelector('[data-book-submit]');
    if (button) { button.disabled = true; button.textContent = 'Reserving your appointment…'; }
    form.querySelector('[data-book-status]').textContent = 'Checking availability and saving your visit. Please keep this page open.';
  });
}
window.addEventListener('pageshow', () => {
  for (const button of document.querySelectorAll('[data-book-submit]')) {
    button.disabled = false; button.textContent = 'Confirm in-person appointment ↗';
  }
});
