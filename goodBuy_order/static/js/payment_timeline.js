// static/js/payment_timeline.js
(function () {
  console.log("[timeline] payment_timeline.js loaded");

  // ---------- color helpers (for pie charts) ----------
  const EXPENSE_BASE = { h: 12, s: 82, l: 54 };  // 橘紅（支出）
  const INCOME_BASE  = { h: 205, s: 75, l: 50 }; // 藍色（收入）
  const hsl = (h, s, l) => `hsl(${h}, ${s}%, ${l}%)`;
  const makePalette = (base, n) => {
    const arr = [];
    for (let i = 0; i < n; i++) {
      const hue   = (base.h + i * 12) % 360;
      const light = Math.max(30, Math.min(72, base.l + (i % 2 ? -10 : 8) - Math.floor(i / 2) * 4));
      arr.push(hsl(hue, base.s, light));
    }
    return arr;
  };

  // DOM ready
  const ready = (fn) => {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  };

  ready(() => {
    const btnLine = document.getElementById("btnLine");
    const btnPie  = document.getElementById("btnPie");
    const chartsSection = document.getElementById("chartsSection");

    if (!btnLine || !btnPie) {
      console.error("[timeline] buttons not found");
      return;
    }
    if (!window.GB) {
      console.error("[timeline] window.GB undefined");
      return;
    }

    let lineChart;
    let pieChartExp, pieChartInc;

    // 顯示圖表區（由 CSS 控制大小），顯示後再 new Chart
    function ensureShown() {
      if (!chartsSection) return;
      if (chartsSection.style.display === "none" || getComputedStyle(chartsSection).display === "none") {
        chartsSection.style.display = "block";
      }
    }

    // 共用的 Chart.js options（交給父容器高度）
    const commonOpts = {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { position: "top" },
        tooltip: { intersect: false, mode: "index" }
      }
    };

    // ========== 折線圖 ==========
    btnLine.addEventListener("click", async () => {
      try {
        console.log("[timeline] line clicked ->", GB.lineUrl, "year=", GB.defaultYear);
        ensureShown();

        const res = await fetch(`${GB.lineUrl}?year=${encodeURIComponent(GB.defaultYear)}`, {
          headers: { "X-Requested-With": "fetch" }
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        const c = document.getElementById("lineChart");
        if (!c) return;
        const ctx = c.getContext("2d");

        if (lineChart) { lineChart.destroy(); lineChart = null; }

        // 建立折線圖
        lineChart = new Chart(ctx, {
          type: "line",
          data: {
            labels: (data.months || []).map(m => `${m}月`),
            datasets: [
              {
                label: "收入",
                data: data.income || [],
                borderWidth: 2,
                tension: 0.25,
                fill: false
              },
              {
                label: "支出",
                data: data.expense || [],
                borderWidth: 2,
                tension: 0.25,
                fill: false
              },
              {
                label: "月淨額",
                data: data.net || [],
                borderDash: [6, 4],
                borderWidth: 2,
                tension: 0.25,
                fill: false
              },
              {
                label: "累計淨額",
                data: data.cum_net || [],
                borderWidth: 2,
                pointRadius: 2,
                tension: 0.15,
                fill: false
              }
            ]
          },
          options: {
            ...commonOpts,
            scales: {
              x: { ticks: { maxRotation: 0 } },
              y: { beginAtZero: true }
            }
          }
        });

        // 若一開始在 display:none 建立，顯示後再 resize 一次保險
        lineChart.resize();
      } catch (err) {
        console.error("[timeline] line error", err);
        alert("載入折線圖失敗：" + err.message);
      }
    });

    // ========== 圓餅圖（支出 / 收入） ==========
    btnPie.addEventListener("click", async () => {
      try {
        console.log("[timeline] pie clicked ->", GB.pieUrl, "year=", GB.defaultYear, "month=", GB.defaultMonth);
        ensureShown();

        const q = new URLSearchParams({
          year: String(GB.defaultYear ?? ""),
          month: String(GB.defaultMonth ?? "")
        }).toString();

        const res = await fetch(`${GB.pieUrl}?${q}`, {
          headers: { "X-Requested-With": "fetch" }
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const json = await res.json();
        console.log("[timeline] pie data", json);

        const exp = json.expense || { labels: [], values: [], total: 0 };
        const inc = json.income  || { labels: [], values: [], total: 0 };

        const metaExp = document.getElementById("pieMetaExpense");
        const metaInc = document.getElementById("pieMetaIncome");
        if (metaExp) metaExp.textContent = (exp.total && exp.values.length)
          ? `總支出：${exp.total}（Top ${exp.labels.length} + 其他）`
          : "本期沒有支出資料";
        if (metaInc) metaInc.textContent = (inc.total && inc.values.length)
          ? `總收入：${inc.total}（Top ${inc.labels.length} + 其他）`
          : "本期沒有收入資料";

        const canvasExp = document.getElementById("pieChartExpense");
        const canvasInc = document.getElementById("pieChartIncome");
        if (!canvasExp || !canvasInc) return;

        const ctxExp = canvasExp.getContext("2d");
        const ctxInc = canvasInc.getContext("2d");

        if (pieChartExp) { pieChartExp.destroy(); pieChartExp = null; }
        if (pieChartInc) { pieChartInc.destroy(); pieChartInc = null; }

        const clearCanvas = (ctx) => {
          const c = ctx.canvas;
          ctx.clearRect(0, 0, c.width, c.height);
        };

        // 支出餅（橘紅系）
        if (exp.total && exp.values.length) {
          const colorsExp = makePalette(EXPENSE_BASE, exp.labels.length);
          pieChartExp = new Chart(ctxExp, {
            type: "pie",
            data: {
              labels: exp.labels,
              datasets: [{ data: exp.values, backgroundColor: colorsExp, borderWidth: 0 }]
            },
            options: { ...commonOpts }
          });
          pieChartExp.resize();
        } else {
          clearCanvas(ctxExp);
        }

        // 收入餅（藍色系）
        if (inc.total && inc.values.length) {
          const colorsInc = makePalette(INCOME_BASE, inc.labels.length);
          pieChartInc = new Chart(ctxInc, {
            type: "pie",
            data: {
              labels: inc.labels,
              datasets: [{ data: inc.values, backgroundColor: colorsInc, borderWidth: 0 }]
            },
            options: { ...commonOpts }
          });
          pieChartInc.resize();
        } else {
          clearCanvas(ctxInc);
        }
      } catch (err) {
        console.error("[timeline] pie error", err);
        alert("載入圓餅圖失敗：" + err.message);
      }
    });

    // 視窗縮放：主動 resize，避免 RWD 切換時比例不對
    window.addEventListener("resize", () => {
      if (lineChart)    lineChart.resize();
      if (pieChartExp)  pieChartExp.resize();
      if (pieChartInc)  pieChartInc.resize();
    });
  });
})();
