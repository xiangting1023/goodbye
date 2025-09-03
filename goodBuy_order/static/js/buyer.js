console.log('[buyer.js] loaded');

document.addEventListener('DOMContentLoaded', () => {
  const buttons = document.querySelectorAll('.action-btn[data-tab]');
  const tabNames = Array.from(buttons).map(b => b.dataset.tab).filter(Boolean);

  if (tabNames.length === 0) {
    console.warn('[buyer.js] no tabs found');
    return;
  }

  function panelEl(name) {
    return document.getElementById('tab-' + name);
  }

  function showTab(tabName) {
    // 顯示/隱藏面板
    tabNames.forEach(name => {
      const el = panelEl(name);
      if (!el) return;
      const active = name === tabName;
      el.classList.toggle('d-none', !active);
      el.style.display = active ? '' : 'none';
    });

    // 按鈕樣式 + ARIA
    buttons.forEach(btn => {
      const isActive = btn.dataset.tab === tabName;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-controls', 'tab-' + btn.dataset.tab);
    });

    // 更新 hash（保留 query）
    const url = location.pathname + location.search + '#' + tabName;
    if (location.hash !== '#' + tabName) history.replaceState(null, '', url);
  }

  // 綁定點擊（只用 data-tab）
  buttons.forEach(btn => {
    btn.addEventListener('click', () => showTab(btn.dataset.tab));
  });

  // 初始：hash 優先，否則第一顆
  const initial = (location.hash || '').slice(1);
  const start = tabNames.includes(initial) ? initial : tabNames[0];
  showTab(start);

  // 返回鍵 / 手動改 hash
  window.addEventListener('hashchange', () => {
    const current = (location.hash || '').slice(1);
    if (tabNames.includes(current)) showTab(current);
  });

  // POST 後回到同一分頁：把 hash 補進 hidden next
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    const nextInput = form.querySelector('input[name="next"]');
    if (nextInput) {
      const hash = location.hash || '';
      if (hash && !nextInput.value.includes('#')) nextInput.value += hash;
    }
  });
});
