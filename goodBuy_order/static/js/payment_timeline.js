// static/js/payment_timeline.js
(function () {
  console.log('[timeline] payment_timeline.js loaded');

  const ready = (fn) => {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  };

  ready(() => {
    const btnLine = document.getElementById('btnLine');
    const btnPie  = document.getElementById('btnPie');
    const chartsSection = document.getElementById('chartsSection');

    if (!btnLine || !btnPie) {
      console.error('[timeline] buttons not found');
      return;
    }
    if (!window.GB) {
      console.error('[timeline] window.GB undefined');
      return;
    }

    let lineChart, pieChart;

    function ensureShown() {
      if (chartsSection && chartsSection.style.display === 'none') {
        chartsSection.style.display = 'block';
      }
    }

    btnLine.addEventListener('click', async () => {
      try {
        console.log('[timeline] line clicked ->', GB.lineUrl, 'year=', GB.defaultYear);
        ensureShown();
        const res = await fetch(`${GB.lineUrl}?year=${GB.defaultYear}`, {
          headers: { 'X-Requested-With': 'fetch' }
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        const ctx = document.getElementById('lineChart').getContext('2d');
        if (lineChart) lineChart.destroy();
        lineChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: data.months.map(m => `${m}月`),
            datasets: [
              { label: '收入', data: data.income },
              { label: '支出', data: data.expense },
              { label: '月淨額', data: data.net },
              { label: '累計淨額', data: data.cum_net }
            ]
          },
          options: { responsive: true, interaction: { mode: 'index', intersect: false } }
        });
      } catch (err) {
        console.error('[timeline] line error', err);
        alert('載入折線圖失敗：' + err.message);
      }
    });

    btnPie.addEventListener('click', async () => {
      try {
        console.log('[timeline] pie clicked ->', GB.pieUrl, 'year=', GB.defaultYear, 'month=', GB.defaultMonth);
        ensureShown();
        const q = new URLSearchParams({ year: GB.defaultYear, month: GB.defaultMonth }).toString();
        const res = await fetch(`${GB.pieUrl}?${q}`, {
          headers: { 'X-Requested-With': 'fetch' }
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();

        const exp = json.expense || { labels: [], values: [], total: 0 };
        const meta = document.getElementById('pieMeta');
        if (meta) meta.textContent = `總支出：${exp.total}（Top ${exp.labels.length} + 其他）`;

        const ctx = document.getElementById('pieChart').getContext('2d');
        if (pieChart) pieChart.destroy();
        pieChart = new Chart(ctx, {
          type: 'pie',
          data: { labels: exp.labels, datasets: [{ data: exp.values }] },
          options: { responsive: true }
        });
      } catch (err) {
        console.error('[timeline] pie error', err);
        alert('載入圓餅圖失敗：' + err.message);
      }
    });
  });
})();
