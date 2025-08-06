window.addEventListener("DOMContentLoaded", () => {
  const header = document.querySelector('.header');
  const content = document.querySelector('.main-content');
  if (header && content) {
    content.style.marginTop = header.offsetHeight + 'px';
  }
});