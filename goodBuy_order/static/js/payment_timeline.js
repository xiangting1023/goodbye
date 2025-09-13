(function() {
  if (!window.GB) { alert('圖表初始化失敗：找不到 API'); return; }
  const URL_LINE = window.GB.lineUrl;
  const URL_PIE  = window.GB.pieUrl;

  const btnLine = document.getElementById('btnLine');
  const btnPie  = document.getElementById('btnPie');

  // 取「年 / 月」值：你頁面上已有 #filterForm 的 2 個 <select>
  const form = document.getElementById('filterForm');
  const yearSelect  = form?.querySelector('select[name="year"]');
  const monthSelect = form?.querySelector('select[name="month"]');

  let lineChart, pieChart;

  async function fetchJSON(url) {
    const res = await fetch(url, { credentials: 'same-origin' });
    const ct = res.headers.get('content-type') || '';
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (!ct.includes('application/json')) {
      const t = await res.text(); console.error('非 JSON 回應：', t.slice(0,300));
      throw new Error('伺服器回傳非 JSON（可能被導向登入頁或錯誤頁）');
    }
    return res.json();
  }

  function getYM() {
    return {
      year: parseInt(yearSelect?.value || new Date().getFullYear(), 10),
      month: parseInt(monthSelect?.value || (new Date().getMonth()+1), 10),
    };
  }

  async function loadLineChart() {
    const { year } = getYM();
    const u = new URL(URL_LINE, window.location.origin);
    u.searchParams.set('year', year);

    const data = await fetchJSON(u);
    const ctx = document.getElementById('lineChart').getContext('2d');
    if (lineChart) lineChart.destroy();

    lineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.months.map(m => `${m}月`),
        datasets: [
          { label: '收入',     data: data.income,  tension: 0.25 },
          { label: '支出',     data: data.expense, tension: 0.25 },
          { label: '淨額',     data: data.net,     tension: 0.25 },
          { label: '累積淨額', data: data.cum_net, tension: 0.25 },
        ]
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'top' } }
      }
    });
  }

  async function loadPieChart() {
    const { year, month } = getYM();
    const u = new URL(URL_PIE, window.location.origin);
    u.searchParams.set('year', year);
    u.searchParams.set('month', month);

    const payload = await fetchJSON(u);
    const ctx = document.getElementById('pieChart').getContext('2d');
    if (pieChart) pieChart.destroy();

    pieChart = new Chart(ctx, {
      type: 'pie',
      data: { labels: payload.labels, datasets: [{ data: payload.values }] },
      options: { responsive: true, plugins: { legend: { position: 'right' } } }
    });

    const ym = payload.scope.month ? `${payload.scope.year} 年 ${payload.scope.month} 月` : `${payload.scope.year} 年（全年）`;
    document.getElementById('pieMeta').textContent =
      `期間：${ym} ｜ 總支出：${Number(payload.total).toLocaleString()} $`;
  }

  // 綁事件
  btnLine?.addEventListener('click', () => loadLineChart().catch(e => alert('載入折線圖失敗：' + e.message)));
  btnPie ?.addEventListener('click', () => loadPieChart ().catch(e => alert('載入圓餅圖失敗：' + e.message)));

  // 進頁就各畫一次（可選）
  loadLineChart().catch(console.error);
  loadPieChart().catch(console.error);
})();
