(function() {
  // 0) 讀模板注入的 URL，沒有就直接報錯
  if (!window.GB || !window.GB.lineUrl || !window.GB.pieUrl) {
    console.error('window.GB 未正確初始化。請確認 HTML 有注入 lineUrl / pieUrl。');
    alert('圖表初始化失敗：找不到 API 位址（window.GB）。');
    return;
  }
  const URL_LINE = window.GB.lineUrl;
  const URL_PIE  = window.GB.pieUrl;

  // 1) DOM
  const btnLine = document.getElementById('btnLine');
  const btnPie  = document.getElementById('btnPie');
  const chartsSection = document.getElementById('chartsSection');
  const form = document.getElementById('filterForm');
  if (!form) {
    console.error('找不到 #filterForm。');
    return;
  }
  const yearSelect  = form.querySelector('select[name="year"]');
  const monthSelect = form.querySelector('select[name="month"]');

  let lineChartInstance = null;
  let pieChartInstance  = null;

  function getSelections() {
    return {
      year: parseInt(yearSelect.value, 10),
      month: parseInt(monthSelect.value, 10)
    };
  }

  function showChartsSection() {
    chartsSection.style.display = 'block';
    chartsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // 2) 比較安全的 fetch JSON：偵測被導到登入頁、404 等
  async function fetchJSON(url) {
    const res = await fetch(url, { credentials: 'same-origin', redirect: 'follow' });
    const ct = res.headers.get('content-type') || '';
    if (!res.ok) {
      // 例如 404/500
      const text = await res.text();
      console.error('HTTP 非 2xx：', res.status, res.statusText, text.slice(0, 300));
      throw new Error(`HTTP ${res.status} ${res.statusText}`);
    }
    if (!ct.includes('application/json')) {
      // 例如被 @login_required 導去 /login/，或 URL 打錯拿到 HTML
      const text = await res.text();
      console.error('非 JSON 回應（很可能是登入頁或 404 頁）：', text.slice(0, 300));
      throw new Error('伺服器回傳非 JSON，請確認已登入與路由名稱正確。');
    }
    return res.json();
  }

  // 3) 折線圖
  async function loadLineChart() {
    try {
      const { year } = getSelections();
      const url = new URL(URL_LINE, window.location.origin);
      url.searchParams.set('year', year);

      console.log('[LINE] GET', url.toString());
      const data = await fetchJSON(url);

      const ctx = document.getElementById('lineChart').getContext('2d');
      if (lineChartInstance) lineChartInstance.destroy();

      const labels = data.months.map(m => `${m}月`);
      lineChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            { label: '收入',     data: data.income,  tension: 0.25 },
            { label: '支出',     data: data.expense, tension: 0.25 },
            { label: '淨額',     data: data.net,     tension: 0.25 },
            { label: '累積淨額', data: data.cum_net, tension: 0.25 }
          ]
        },
        options: {
          responsive: true,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { position: 'top' } }
        }
      });
      showChartsSection();
    } catch (err) {
      console.error('載入折線圖失敗：', err);
      alert('載入折線圖失敗：' + err.message);
    }
  }

  // 4) 圓餅圖
  async function loadPieChart() {
    try {
      const { year, month } = getSelections();
      const url = new URL(URL_PIE, window.location.origin);
      url.searchParams.set('year', year);
      url.searchParams.set('month', month);

      console.log('[PIE] GET', url.toString());
      const { labels, values, total, scope } = await fetchJSON(url);

      const ctx = document.getElementById('pieChart').getContext('2d');
      if (pieChartInstance) pieChartInstance.destroy();

      pieChartInstance = new Chart(ctx, {
        type: 'pie',
        data: { labels, datasets: [{ data: values }] },
        options: { responsive: true, plugins: { legend: { position: 'right' } } }
      });

      const ymText = scope.month ? `${scope.year} 年 ${scope.month} 月` : `${scope.year} 年（全年）`;
      document.getElementById('pieMeta').textContent =
        `期間：${ymText}　|　總支出：${Number(total).toLocaleString()} $`;

      showChartsSection();
    } catch (err) {
      console.error('載入圓餅圖失敗：', err);
      alert('載入圓餅圖失敗：' + err.message);
    }
  }

  // 5) 綁事件
  if (btnLine) btnLine.addEventListener('click', loadLineChart);
  if (btnPie)  btnPie.addEventListener('click',  loadPieChart);
})();
