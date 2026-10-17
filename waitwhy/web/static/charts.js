/* Shared chart setup (Chart.js 4). Colours come from the CSS tokens in app.css, so light and dark mode
   each get their own validated steps; charts are rebuilt when the theme changes. Platforms always keep
   the same colour (YouTube blue, Instagram orange, TikTok aqua), whatever is filtered. */
(function () {
  const builders = [];
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const platformColor = p => css('--c-' + p) || css('--c-other');
  const fmt = v => v == null ? '—' : (Math.abs(v) >= 10000 ? (v / 1000).toFixed(1) + 'k' : Math.round(v).toLocaleString());
  const NAMES = { youtube: 'YouTube', instagram: 'Instagram', tiktok: 'TikTok', facebook: 'Facebook' };
  const pname = p => NAMES[p] || p.charAt(0).toUpperCase() + p.slice(1);
  const when = (iso, stepH) => {
    const d = new Date(iso);
    const day = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    return stepH >= 24 ? day : day + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  };
  /* Break a long category label into lines of about 16 characters so every bar keeps its name. */
  const wrap = t => t.split(' ').reduce((lines, w) => {
    const last = lines[lines.length - 1];
    if (last && (last + ' ' + w).length <= 16) lines[lines.length - 1] = last + ' ' + w; else lines.push(w);
    return lines;
  }, []);

  function base(yFmt) {
    const grid = css('--grid'), muted = css('--muted');
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: css('--surface'), titleColor: css('--text'), bodyColor: css('--text'),
          borderColor: css('--border'), borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
          callbacks: { label: c => ` ${c.dataset.label}: ${(yFmt || fmt)(c.parsed.y ?? c.parsed.x)}` }
        }
      },
      scales: {
        x: { grid: { display: false }, border: { color: grid }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 12, font: { size: 12 } } },
        y: { beginAtZero: true, grid: { color: grid }, border: { display: false },
             ticks: { color: muted, font: { size: 12 }, maxTicksLimit: 5, callback: v => (yFmt || fmt)(v) } }
      }
    };
  }

  function make(id, build) {
    const el = document.getElementById(id);
    if (!el || !window.Chart) return;
    let chart = null;
    const render = () => { if (chart) chart.destroy(); chart = new Chart(el, build()); };
    builders.push(render);
    render();
  }

  /* Views over time, one line per platform. data = {days: [iso...], step_h, series: {platform: [...]}} */
  function timeline(id, data) {
    make(id, () => ({
      type: 'line',
      data: {
        labels: data.days.map(d => when(d, data.step_h)),
        datasets: Object.entries(data.series).map(([p, vals]) => ({
          label: pname(p), data: vals, borderColor: platformColor(p),
          backgroundColor: platformColor(p), borderWidth: 2, pointRadius: data.days.length > 20 ? 0 : 3,
          pointHoverRadius: 5, pointBorderColor: css('--surface'), pointBorderWidth: 2, cubicInterpolationMode: 'monotone'
        }))
      },
      options: base()
    }));
  }

  /* Vertical bars, one or more named series with explicit colour tokens. */
  function bars(id, labels, series, yFmt) {
    make(id, () => {
      const o = base(yFmt);
      o.interaction = { mode: 'index', intersect: false };
      o.scales.x.ticks = { ...o.scales.x.ticks, autoSkip: false };
      o.plugins.tooltip.callbacks.title = items => labels[items[0].dataIndex];
      return {
        type: 'bar',
        data: {
          labels: labels.map(wrap),
          datasets: series.map(s => ({
            label: s.label, data: s.data, backgroundColor: css(s.color), borderRadius: 4,
            borderSkipped: 'start', maxBarThickness: 36, categoryPercentage: 0.7, barPercentage: 0.9
          }))
        },
        options: o
      };
    });
  }

  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  (mq.addEventListener ? mq.addEventListener.bind(mq, 'change') : mq.addListener.bind(mq))(() => builders.forEach(b => b()));

  window.ww = { timeline, bars, fmt, platformColor };
})();
