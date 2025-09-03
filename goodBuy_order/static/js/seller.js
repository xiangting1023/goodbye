console.log('[seller.js] loaded');
document.addEventListener('DOMContentLoaded', () => {
    const tabs = ['order', 'payment', 'shipping'];
    const buttons = document.querySelectorAll('.action-btn');
  
    // 可選擇：用 d-none 隱藏（Bootstrap），或改回 style.display
    function showTab(tabName) {
      tabs.forEach(name => {
        const el = document.getElementById('tab-' + name);
        if (!el) return;
        if (name === tabName) {
          el.classList.remove('d-none');
          el.style.display = '';
        } else {
          el.classList.add('d-none');
          el.style.display = 'none';
        }
      });
  
      // 切換按鈕樣式 + ARIA
      buttons.forEach(btn => {
        const isActive = btn.getAttribute('data-tab') === tabName;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
  
      // 更新網址 hash（保留 query string）
      const base = location.pathname + location.search + '#' + tabName;
      if (location.hash !== '#' + tabName) {
        history.replaceState(null, '', base);
      }
    }
  
    // 點擊切換
    buttons.forEach(btn => {
      // ARIA 對應
      const tabName = btn.getAttribute('data-tab');
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-controls', 'tab-' + tabName);
  
      btn.addEventListener('click', () => showTab(tabName));
    });
  
    // 依 hash 初始顯示；沒有則顯示第一個
    const initial = (location.hash || '').replace('#', '');
    if (tabs.includes(initial)) {
      showTab(initial);
    } else if (buttons[0]) {
      showTab(buttons[0].getAttribute('data-tab'));
    }
  
    // 支援使用者手動改 hash 或瀏覽器返回鍵
    window.addEventListener('hashchange', () => {
      const current = (location.hash || '').replace('#', '');
      if (tabs.includes(current)) showTab(current);
    });
  });
  