  // 自動淡出與關閉 Bootstrap alerts
(function () {
  const AUTO_CLOSE_MS = 1000;
  const alerts = document.querySelectorAll('.alert.auto-fade');

  alerts.forEach((el, idx) => {
    // 依序錯開一點點時間
    const delay = AUTO_CLOSE_MS + idx * 150;
    setTimeout(() => {
      // 漸隱
      el.classList.remove('show');
      // 動畫結束後真正關閉
      setTimeout(() => {
        if (window.bootstrap) {
          const inst = bootstrap.Alert.getOrCreateInstance(el);
          inst.close();
        } else {
          el.remove();
        }
      }, 500); // 對應 Bootstrap 的淡出時間
    }, delay);
  });
})();