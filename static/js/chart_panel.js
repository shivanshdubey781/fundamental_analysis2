/* ═══════════════════════════════════════════════════════════════════════════
   FLOATING CHART PANEL ENGINE  —  chart_panel.js
   ─────────────────────────────────────────────────────────────────────────
   Features:
   · OHLC candlestick chart drawn on <canvas>
   · Astro transit zone overlays (Upside = light-green, Downside = light-red)
   · LTP dashed-line overlay with badge
   · Interactive crosshair + OHLC tooltip
   · Drag-to-reposition (mouse + touch)
   · Expand / collapse
   · Range selector (5D, 1M, 3M, 6M, 1Y)  — fetches from /api/stock
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── State ──────────────────────────────────────────────────────────────── */
const _cp = {
  ticker:      '',
  sector:      '',
  astroStatus: 'Neutral',    // 'Upside' | 'Neutral' | 'Downside'
  astroScore:  3,
  planets:     'Jup',
  range:       '1d',         // '1d' (daily candles) is the visual default
  viewportOffset: 0,         // offset for scrolling back through history
  priceData:   [],           // [{date,open,high,low,close,volume}, ...]
  ltp:         null,
  chg:         null,
  chgPct:      null,
  meta:        null,         // drawing geometry cached for crosshair
  showAstro:   true,
  expanded:    false,
  dragging:    false,
  dStartX: 0, dStartY: 0, dStartL: 0, dStartT: 0,
  loading:     false,
};

/* ── Helpers ────────────────────────────────────────────────────────────── */
const _cpFmt  = v => (v == null || isNaN(+v)) ? '—' : Number(v).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2});
const _cpFmt1 = v => (v == null || isNaN(+v)) ? '—' : Number(v).toFixed(1);
const _cpMono = '"IBM Plex Mono",monospace';

function _cpResize(id) {
  const canvas = document.getElementById(id);
  const stage  = document.getElementById('cpStage');
  const rect   = stage.getBoundingClientRect();
  const dpr    = window.devicePixelRatio || 1;
  const w = Math.max(200, Math.floor(rect.width));
  const h = Math.max(100, Math.floor(rect.height));
  canvas.width  = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width  = w + 'px';
  canvas.style.height = h + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function _cpClearCanvas(id) {
  const c = document.getElementById(id);
  if (!c) return;
  c.getContext('2d').clearRect(0, 0, c.width, c.height);
}

function _cpHighlightActiveRangeButton() {
  const chips = document.querySelectorAll('.cp-chip[data-range]');
  chips.forEach(btn => {
    if (btn.getAttribute('data-range') === _cp.range) {
      btn.classList.add('on');
    } else {
      btn.classList.remove('on');
    }
  });
}

/* ── Entry point: called from screener row onclick ─────────────────────── */
function openCpFromRow(event, ticker, sector, transitStatus, planets, astroScore) {
  _cp.ticker      = ticker;
  _cp.sector      = sector || '';
  _cp.astroStatus = transitStatus || 'Neutral';
  _cp.planets     = planets || 'Jup';
  _cp.astroScore  = Number(astroScore) || 3;
  _cp.priceData   = [];
  _cp.meta        = null;

  // Open the floating chart panel
  _cpShowPanel();
  _cpUpdateHeader();
  _cpHighlightActiveRangeButton();
  _cpLoadData();

  // ALSO load the full detail / analysis report in the sidebar
  loadTicker(ticker);
}

/* Also callable from sector cards' TOP PICKS (ticker only) */
function openCpByTicker(ticker) {
  // look up astro data from cached screener results
  const row = (_screenerData || []).find(r => r.ticker === ticker);
  if (row) {
    openCpFromRow(null, ticker, row.sector || '', row.transit_status || 'Neutral', row.ruling_planets || 'Jup', row.astro_score || 3);
  } else {
    openCpFromRow(null, ticker, '', 'Neutral', 'Jup', 3);
  }
  // Full report also loads via openCpFromRow → loadTicker chain
}

/* ── Show / hide ────────────────────────────────────────────────────────── */
function _cpShowPanel() {
  const panel = document.getElementById('chartPanel');
  panel.style.display = 'flex';
  panel.style.animation = 'cpPanelIn .25s cubic-bezier(.22,.9,.36,1) forwards';

  // inject keyframe once
  if (!document.getElementById('cpKeyframes')) {
    const s = document.createElement('style');
    s.id = 'cpKeyframes';
    s.textContent = `
      @keyframes cpPanelIn {
        from { opacity:0; transform:translateY(18px) scale(.97); }
        to   { opacity:1; transform:translateY(0)    scale(1);   }
      }`;
    document.head.appendChild(s);
  }
}

function closeCp() {
  const panel = document.getElementById('chartPanel');
  panel.style.display = 'none';
  _cp.ticker = '';
}

function toggleCpExpand() {
  const panel = document.getElementById('chartPanel');
  _cp.expanded = !_cp.expanded;
  if (_cp.expanded) {
    panel.style.width  = Math.min(1000, window.innerWidth  * 0.92) + 'px';
    panel.style.height = Math.min(660,  window.innerHeight * 0.86) + 'px';
    document.getElementById('cpExpandBtn').textContent = '⤡';
  } else {
    panel.style.width  = '600px';
    panel.style.height = '420px';
    document.getElementById('cpExpandBtn').textContent = '⤢';
  }
  setTimeout(() => { if (_cp.priceData.length) _cpDraw(); }, 240);
}

/* ── Header update ──────────────────────────────────────────────────────── */
function _cpUpdateHeader() {
  document.getElementById('cpTitle').textContent = _cp.ticker;
  document.getElementById('cpSub').textContent   = (_cp.sector || '') + ' · ' + _cp.ticker + '.NSE';
  document.getElementById('cpLiveDot').style.display = 'block';

  const badge  = document.getElementById('cpAstroBadge');
  const st     = _cp.astroStatus;
  const col    = st === 'Upside' ? '#00ff88' : st === 'Downside' ? '#ff5050' : '#ffb400';
  const bg     = st === 'Upside' ? 'rgba(0,255,136,.15)' : st === 'Downside' ? 'rgba(255,80,80,.15)' : 'rgba(255,180,0,.15)';
  const icon   = st === 'Upside' ? '📈' : st === 'Downside' ? '📉' : '➖';
  badge.textContent    = `${icon} ASTRO (${(_cp.planets || 'JUP').toUpperCase()}) · ${st.toUpperCase()}`;
  badge.style.display  = 'inline-block';
  badge.style.color    = col;
  badge.style.background = bg;
  badge.style.border   = `1px solid ${col}44`;
}

/* ── Load price data from backend ──────────────────────────────────────── */
async function _cpLoadData() {
  if (_cp.loading) return;
  _cp.loading = true;

  const empty = document.getElementById('cpEmpty');
  empty.style.display = 'flex';
  empty.textContent   = '⏳ Loading chart data…';
  _cpClearCanvas('cpCanvas');
  _cpClearCanvas('cpLtpCanvas');
  _cpClearCanvas('cpCrossCanvas');
  document.getElementById('cpStats').innerHTML = '';

  try {
    const resp = await fetch(`/api/stock?ticker=${encodeURIComponent(_cp.ticker)}`);
    if (!resp.ok) throw new Error('API error ' + resp.status);
    const payload = await resp.json();

    const raw = Array.isArray(payload.price_data) ? payload.price_data : [];
    if (!raw.length) throw new Error('No price data returned');

    // Normalise to our format — store the full history
    _cp.fullData = raw.map(d => ({
      date:  d.date,
      open:  Number(d.open  || d.adjusted_close || d.close),
      high:  Number(d.high  || d.adjusted_close || d.close),
      low:   Number(d.low   || d.adjusted_close || d.close),
      close: Number(d.close || d.adjusted_close),
      vol:   Number(d.volume || 0),
    })).filter(d => isFinite(d.close) && d.close > 0);

    // Apply range slice
    _cp.viewportOffset = 0;
    _cp.priceData = _cpSliceByRange(_cp.fullData, _cp.range);
    cpUpdateScrollbar();

    // LTP
    _cp.ltp = payload.ltp?.value || _cp.priceData[_cp.priceData.length - 1]?.close || null;

    // Compute change vs first in window
    const first = _cp.priceData[0];
    const last  = _cp.priceData[_cp.priceData.length - 1];
    _cp.chg    = last.close - first.close;
    _cp.chgPct = ((_cp.chg) / first.close) * 100;

    // Pull astro from composite if missing
    const cmp = payload.composite;
    if (cmp?.astro_sc) {
      _cp.astroStatus = cmp.astro_sc.transit_status || _cp.astroStatus;
      _cp.planets     = cmp.astro_sc.ruling_planets || _cp.planets;
      _cp.astroScore  = cmp.astro_sc.astro_score    || _cp.astroScore;
      _cpUpdateHeader();
    }

    empty.style.display = 'none';
    _cpRenderStats();
    _cpDraw();

  } catch(e) {
    empty.style.display = 'flex';
    empty.textContent   = '⚠ ' + (e.message || 'Failed to load chart');
  } finally {
    _cp.loading = false;
  }
}

/* ── Stats strip ────────────────────────────────────────────────────────── */
function _cpRenderStats() {
  const up  = _cp.chg >= 0;
  const pd  = _cp.priceData;
  const high = Math.max(...pd.map(d => d.high));
  const low  = Math.min(...pd.map(d => d.low));

  const stat = (k, v, cls = '') => `
    <div style="padding:6px 14px;border-right:1px solid var(--border);min-width:80px;flex-shrink:0">
      <div style="font-size:9px;color:var(--text3);letter-spacing:.09em;text-transform:uppercase">${k}</div>
      <div style="font-size:13px;font-weight:700;color:${cls || 'var(--text)'};margin-top:2px;font-family:${_cpMono}">${v}</div>
    </div>`;

  document.getElementById('cpStats').innerHTML =
    stat('LTP',    _cpFmt(_cp.ltp)) +
    stat('CHG',    (up?'+':'')+_cpFmt(_cp.chg),  up?'#00ff88':'#ff5050') +
    stat('CHG %',  (up?'+':'')+_cpFmt1(_cp.chgPct)+'%', up?'#00ff88':'#ff5050') +
    stat('HIGH',   _cpFmt(high)) +
    stat('LOW',    _cpFmt(low)) +
    stat('ASTRO',  _cp.astroStatus,
      _cp.astroStatus==='Upside'?'#00ff88':_cp.astroStatus==='Downside'?'#ff5050':'#ffb400');
}

/* ── Main draw ──────────────────────────────────────────────────────────── */
function _cpDraw() {
  const { ctx, w, h } = _cpResize('cpCanvas');
  _cpClearCanvas('cpCrossCanvas');
  _cpHideTooltip();

  const cs = _cp.priceData.filter(d => isFinite(d.close));
  const UP   = '#4fffb0';
  const DN   = '#ff4466';
  const GRID = 'rgba(255,255,255,.04)';
  const TXT  = 'rgba(255,255,255,.2)';

  // Background
  ctx.fillStyle = '#080a12';
  ctx.fillRect(0, 0, w, h);

  if (!cs.length) return;

  const highs = cs.map(d => d.high);
  const lows  = cs.map(d => d.low);
  if (_cp.ltp != null) {
    highs.push(_cp.ltp);
    lows.push(_cp.ltp);
  }
  const maxV = Math.max(...highs);
  const minV = Math.min(...lows);
  const rng  = maxV - minV || 1;

  ctx.font = `10px ${_cpMono}`;
  const leftW  = Math.max(68, Math.ceil(ctx.measureText(_cpFmt(maxV)).width) + 16);
  const rightW = 86; // 86px margin gives plenty of space for the LTP price badge on the right
  const PAD_T  = 18;
  const PAD_B  = 30;
  const plotW  = w - leftW - rightW;
  const plotH  = h - PAD_T - PAD_B;
  const left   = leftW;
  const top    = PAD_T;
  const bottom = top + plotH;

  const scale = v => bottom - ((Number(v) - minV) / rng) * plotH;

  /* ── Astro zone shading — drawn FIRST (below candles) ──────────────── */
  if (_cp.showAstro && _cp.astroStatus !== 'Neutral') {
    const zoneCol = _cp.astroStatus === 'Upside'
      ? 'rgba(0,255,136,.06)'
      : 'rgba(255,68,68,.06)';
    const zoneBrd = _cp.astroStatus === 'Upside'
      ? 'rgba(0,255,136,.18)'
      : 'rgba(255,68,68,.18)';
    const zoneLabel = _cp.astroStatus === 'Upside'
      ? `★ ASTRO UPSIDE — ${_cp.planets.toUpperCase()}`
      : `★ ASTRO DOWNSIDE — ${_cp.planets.toUpperCase()}`;
    const zoneTxt = _cp.astroStatus === 'Upside' ? '#00ff88' : '#ff5050';

    // Shade the entire plot area with a subtle gradient
    const grad = ctx.createLinearGradient(left, top, left, bottom);
    grad.addColorStop(0,   zoneCol.replace(',.06)', ',.10)'));
    grad.addColorStop(0.5, zoneCol);
    grad.addColorStop(1,   zoneCol.replace(',.06)', ',.03)'));
    ctx.fillStyle = grad;
    ctx.fillRect(left, top, plotW, plotH);

    // Top border line
    ctx.save();
    ctx.strokeStyle = zoneBrd;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(left, top + 1); ctx.lineTo(left + plotW, top + 1);
    ctx.stroke();
    ctx.restore();

    // Bottom border line
    ctx.save();
    ctx.strokeStyle = zoneBrd;
    ctx.lineWidth   = 1;
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(left, bottom - 1); ctx.lineTo(left + plotW, bottom - 1);
    ctx.stroke();
    ctx.restore();

    // Label inside chart (top-right)
    ctx.save();
    ctx.font      = `bold 9px ${_cpMono}`;
    ctx.fillStyle = zoneTxt;
    ctx.globalAlpha = 0.65;
    ctx.textAlign = 'right';
    ctx.fillText(zoneLabel, left + plotW - 6, top + 14);
    ctx.restore();
  }

  /* ── Grid lines ─────────────────────────────────────────────────────── */
  const ROWS = 5;
  ctx.strokeStyle = GRID;
  ctx.lineWidth   = 1;
  ctx.fillStyle   = TXT;
  ctx.textAlign   = 'right';
  ctx.font = `10px ${_cpMono}`;
  for (let i = 0; i <= ROWS; i++) {
    const y   = top + (plotH / ROWS) * i;
    const val = maxV - (rng / ROWS) * i;
    ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + plotW, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillText(_cpFmt(val), left - 4, y + 3);
  }

  /* ── Time labels ────────────────────────────────────────────────────── */
  ctx.fillStyle  = TXT;
  ctx.textAlign  = 'center';
  ctx.font = `9px ${_cpMono}`;
  const step = Math.max(1, Math.floor(cs.length / 7));
  cs.forEach((c, i) => {
    if (i % step !== 0) return;
    const x = left + (i / Math.max(1, cs.length - 1)) * plotW;
    ctx.fillText(c.date ? c.date.slice(5) : '', x, bottom + 16);
  });

  /* ── Candles ────────────────────────────────────────────────────────── */
  const gap   = plotW / Math.max(1, cs.length);
  const bodyW = Math.max(1.5, Math.min(10, gap * 0.6));

  cs.forEach((c, i) => {
    const o = c.open, h2 = c.high, l = c.low, cl = c.close;
    const bull  = cl >= o;
    const color = bull ? UP : DN;
    const x     = left + i * gap + gap / 2;
    const yH = scale(h2), yL = scale(l), yO = scale(o), yC = scale(cl);

    ctx.strokeStyle = color;
    ctx.fillStyle   = color;
    ctx.lineWidth   = 1;
    ctx.setLineDash([]);

    // Wick
    ctx.beginPath(); ctx.moveTo(x, yH); ctx.lineTo(x, yL); ctx.stroke();

    // Body
    const bTop = Math.min(yO, yC);
    const bH   = Math.max(1.5, Math.abs(yC - yO));
    if (bull) {
      ctx.lineWidth = 1.2;
      ctx.strokeRect(x - bodyW / 2, bTop, bodyW, bH);
    } else {
      ctx.fillRect(x - bodyW / 2, bTop, bodyW, bH);
    }
  });

  // Store geometry for crosshair
  _cp.meta = { cs, left, bottom, plotW, plotH, gap, scale, minV, maxV, rng, top };

  // Dynamically position scrollbar track to align perfectly with plot time-axis
  const scrollContainer = document.getElementById('cpScrollContainer');
  if (scrollContainer) {
    scrollContainer.style.left  = left + 'px';
    scrollContainer.style.right = rightW + 'px';
    scrollContainer.style.display = _cp.fullData && _cp.fullData.length > cs.length ? 'flex' : 'none';
  }

  // Footer
  document.getElementById('cpFootL').textContent =
    `${cs.length} candles · ${_cp.range} · ${_cp.ticker}`;
  document.getElementById('cpFootR').textContent = new Date().toLocaleTimeString('en-IN');

  // LTP
  _cpDrawLtp();
}

/* ── LTP overlay ────────────────────────────────────────────────────────── */
function _cpDrawLtp() {
  const m = _cp.meta;
  if (!m || !_cp.ltp) return;

  const { ctx, w, h } = _cpResize('cpLtpCanvas');
  const { left, plotW, bottom, scale } = m;
  const ltp  = _cp.ltp;
  const yLtp = scale(ltp);
  if (yLtp < 0 || yLtp > h) { return; }

  const isUp  = (_cp.chg || 0) >= 0;
  const color = isUp ? '#00e5a0' : '#ff3b5c';

  // Dashed line
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth   = 1.5;
  ctx.setLineDash([5, 4]);
  ctx.globalAlpha = 0.88;
  ctx.shadowColor = color;
  ctx.shadowBlur  = 6;
  ctx.beginPath();
  ctx.moveTo(left, yLtp); ctx.lineTo(left + plotW, yLtp);
  ctx.stroke();
  ctx.restore();

  // Left triangle marker
  ctx.save();
  ctx.fillStyle   = color;
  ctx.globalAlpha = 0.9;
  ctx.beginPath();
  ctx.moveTo(left, yLtp - 5);
  ctx.lineTo(left - 6, yLtp);
  ctx.lineTo(left, yLtp + 5);
  ctx.closePath(); ctx.fill();
  ctx.restore();

  // Right price badge
  ctx.font = `bold 10px ${_cpMono}`;
  const priceStr  = _cpFmt(ltp);
  const pW        = ctx.measureText(priceStr).width;
  ctx.font = `bold 8px ${_cpMono}`;
  const lW        = ctx.measureText('LTP').width;
  const BPAD = 7, SEP = 4;
  const bW = lW + SEP + pW + BPAD * 2;
  const bH = 18;
  const bX = left + plotW + 2;
  const bY = yLtp - bH / 2;

  ctx.save();
  ctx.fillStyle   = color;
  ctx.globalAlpha = 0.95;
  ctx.fillRect(bX, bY, bW, bH);
  ctx.restore();

  ctx.save();
  ctx.fillStyle   = 'rgba(0,0,0,.85)';
  ctx.font = `bold 8px ${_cpMono}`;
  ctx.textAlign    = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText('LTP', bX + BPAD, yLtp);
  ctx.restore();

  ctx.save();
  ctx.fillStyle   = 'rgba(0,0,0,.9)';
  ctx.font = `bold 10px ${_cpMono}`;
  ctx.textAlign    = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(priceStr, bX + BPAD + lW + SEP + 2, yLtp);
  ctx.restore();
}

/* ── Crosshair ──────────────────────────────────────────────────────────── */
function _cpHideTooltip() {
  const t = document.getElementById('cpTooltip');
  if (t) t.style.display = 'none';
}

function _cpDrawCross(mx, my) {
  const m = _cp.meta;
  if (!m) return;
  const { cs, left, bottom, plotW, plotH, gap, scale } = m;
  const tip   = document.getElementById('cpTooltip');
  const stage = document.getElementById('cpStage');

  if (mx < left || mx > left + plotW || my < 0 || my > bottom) {
    _cpClearCanvas('cpCrossCanvas');
    _cpHideTooltip();
    return;
  }

  const { ctx, w, h } = _cpResize('cpCrossCanvas');
  ctx.clearRect(0, 0, w, h);

  const idx  = Math.max(0, Math.min(cs.length - 1, Math.floor((mx - left) / gap)));
  const c    = cs[idx];
  if (!c) { _cpHideTooltip(); return; }

  const crossX  = left + idx * gap + gap / 2;
  const crossY  = Math.max(0, Math.min(bottom, scale(c.close)));
  const lineC   = 'rgba(0,229,160,.7)';

  // Crosshair lines
  ctx.save();
  ctx.strokeStyle = lineC;
  ctx.lineWidth   = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(crossX, 0); ctx.lineTo(crossX, bottom); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(left, crossY); ctx.lineTo(left + plotW, crossY); ctx.stroke();
  ctx.restore();

  // Price tag (right side)
  const priceStr = _cpFmt(c.close);
  ctx.font = `bold 10px ${_cpMono}`;
  const pW = ctx.measureText(priceStr).width;
  const tH = 18, tW = pW + 12;
  const tX = Math.min(w - tW - 2, left + plotW + 2);
  const tY = Math.max(0, Math.min(bottom - tH/2, crossY - tH/2));
  ctx.fillStyle = 'rgba(0,229,160,.95)';
  ctx.fillRect(tX, tY, tW, tH);
  ctx.fillStyle = '#000';
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  ctx.fillText(priceStr, tX + 6, tY + tH/2 + .5);

  // Date tag (bottom)
  const dateStr = c.date ? c.date.slice(5) : '';
  ctx.font = `9px ${_cpMono}`;
  const dW = ctx.measureText(dateStr).width + 12;
  const dX = Math.max(left, Math.min(left + plotW - dW, crossX - dW/2));
  const dY = bottom + 2;
  ctx.setLineDash([]);
  ctx.fillStyle   = 'rgba(0,229,160,.12)';
  ctx.strokeStyle = 'rgba(0,229,160,.36)';
  ctx.lineWidth   = 1;
  ctx.fillRect(dX, dY, dW, 16);
  ctx.strokeRect(dX, dY, dW, 16);
  ctx.fillStyle = 'rgba(255,255,255,.9)';
  ctx.fillText(dateStr, dX + 6, dY + 8.5);

  // Tooltip card
  const bull = c.close >= c.open;
  const cCol = bull ? '#4fffb0' : '#ff4466';
  tip.style.display = 'block';
  tip.innerHTML = `
    <div style="color:var(--text3);font-size:10px;margin-bottom:4px">${c.date || ''}</div>
    <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:var(--text3)">O</span><span style="font-weight:700">${_cpFmt(c.open)}</span></div>
    <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:var(--text3)">H</span><span style="font-weight:700">${_cpFmt(c.high)}</span></div>
    <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:var(--text3)">L</span><span style="font-weight:700">${_cpFmt(c.low)}</span></div>
    <div style="display:flex;justify-content:space-between;gap:12px"><span style="color:var(--text3)">C</span><span style="font-weight:700;color:${cCol}">${_cpFmt(c.close)}</span></div>
    <div style="display:flex;justify-content:space-between;gap:12px;border-top:1px solid var(--border);margin-top:4px;padding-top:4px"><span style="color:var(--text3)">VOL</span><span style="font-weight:700;font-size:10px">${c.vol >= 1e7 ? (c.vol/1e7).toFixed(2)+'Cr' : c.vol >= 1e5 ? (c.vol/1e5).toFixed(2)+'L' : Math.round(c.vol||0)}</span></div>
  `;
  const sw = stage.offsetWidth;
  const tw = tip.offsetWidth + 14;
  tip.style.left = ((mx + tw > sw) ? mx - tw - 4 : mx + 10) + 'px';
  tip.style.top  = Math.max(4, my - 10) + 'px';
}

/* ── Stage mouse/touch drag-to-scroll events ────────────────────────────── */
(function() {
  const stage = document.getElementById('cpStage');
  if (!stage) return;
  
  let isDragging = false;
  let startX = 0;
  let startOffset = 0;

  function getClientX(e) {
    return e.touches ? e.touches[0].clientX : e.clientX;
  }
  
  function getClientY(e) {
    return e.touches ? e.touches[0].clientY : e.clientY;
  }

  function startDrag(e) {
    if (!_cp.fullData || !_cp.fullData.length) return;
    const size = _cpGetWindowSize(_cp.range);
    if (_cp.fullData.length <= size) return;

    isDragging = true;
    startX = getClientX(e);
    startOffset = _cp.viewportOffset;
    stage.style.cursor = 'grabbing';
  }

  function doDrag(e) {
    const r = stage.getBoundingClientRect();
    const x = getClientX(e) - r.left;
    const y = getClientY(e) - r.top;
    
    if (isDragging) {
      const dx = getClientX(e) - startX;
      const gap = (_cp.meta && _cp.meta.gap) ? _cp.meta.gap : 10;
      // dragging right (dx > 0) scrolls back in history (increases offset)
      // dragging left (dx < 0) scrolls forward in history (decreases offset)
      const candleDelta = Math.round(dx / gap);
      
      const maxOffset = _cp.fullData.length - _cpGetWindowSize(_cp.range);
      _cp.viewportOffset = Math.max(0, Math.min(maxOffset, startOffset + candleDelta));
      _cp.priceData = _cpSliceByRange(_cp.fullData, _cp.range);
      
      // Update visual range slider position
      const scrollbar = document.getElementById('cpScrollbar');
      if (scrollbar) scrollbar.value = maxOffset - _cp.viewportOffset;
      
      _cpDraw();
    } else {
      // Normal hover crosshair drawing
      _cpDrawCross(x, y);
    }
  }

  function endDrag() {
    if (isDragging) {
      isDragging = false;
      stage.style.cursor = 'crosshair';
    }
  }

  // Mouse bindings
  stage.addEventListener('mousedown', startDrag);
  stage.addEventListener('mousemove', doDrag);
  stage.addEventListener('mouseup', endDrag);
  stage.addEventListener('mouseleave', () => {
    endDrag();
    _cpClearCanvas('cpCrossCanvas');
    _cpHideTooltip();
  });

  // Touch bindings (mobile/tablet)
  stage.addEventListener('touchstart', startDrag, { passive: true });
  stage.addEventListener('touchmove', e => {
    if (isDragging) {
      if (e.cancelable) e.preventDefault(); // prevent native scrolling/pull-to-refresh
      doDrag(e);
    }
  }, { passive: false });
  stage.addEventListener('touchend', endDrag);
})();

/* ── Range viewport window sizes ────────────────────────────────────────── */
function _cpGetWindowSize(range) {
  switch (range) {
    case '1d':  return 30;   // 1D default view displays a beautiful trend of 30 daily candles
    case '5d':  return 5;    // last 5 daily candles
    case '1mo': return 22;   // ~1 month (22 daily candles)
    case '3mo': return 66;   // ~3 months (66 daily candles)
    case '6mo': return 130;  // ~6 months (130 daily candles)
    case '1y':  return 200;  // 1 year (full history)
    default:    return 30;
  }
}

/* ── Range slice helper — client-side windowing on the full 200-day history ─ */
function _cpSliceByRange(data, range) {
  if (!data || !data.length) return data;
  const size = _cpGetWindowSize(range);
  const n = data.length;
  
  if (n <= size) {
    _cp.viewportOffset = 0;
    return data;
  }
  
  // Bound viewportOffset
  _cp.viewportOffset = Math.max(0, Math.min(n - size, _cp.viewportOffset));
  
  const end = n - _cp.viewportOffset;
  const start = Math.max(0, end - size);
  return data.slice(start, end);
}

/* ── Scrollbar Controller ─────────────────────────────────────────────────── */
function cpUpdateScrollbar() {
  const scrollbar = document.getElementById('cpScrollbar');
  const container = document.getElementById('cpScrollContainer');
  if (!scrollbar || !_cp.fullData || !_cp.fullData.length) {
    if (container) container.style.display = 'none';
    return;
  }

  const total = _cp.fullData.length;
  const size  = _cpGetWindowSize(_cp.range);

  if (total <= size) {
    if (container) container.style.display = 'none';
    _cp.viewportOffset = 0;
  } else {
    if (container) container.style.display = 'flex';
    scrollbar.max   = total - size;
    scrollbar.value = (total - size) - _cp.viewportOffset; // map rightmost position to latest candles
  }
}

function cpOnScroll(val) {
  if (!_cp.fullData || !_cp.fullData.length) return;
  const total = _cp.fullData.length;
  const size  = _cpGetWindowSize(_cp.range);
  const maxVal = total - size;
  
  _cp.viewportOffset = maxVal - Number(val);
  _cp.priceData = _cpSliceByRange(_cp.fullData, _cp.range);
  
  // Recompute statistics for the new visible window segment
  const first = _cp.priceData[0];
  const last  = _cp.priceData[_cp.priceData.length - 1];
  _cp.chg     = last ? last.close - first.close : 0;
  _cp.chgPct  = first && first.close ? (_cp.chg / first.close) * 100 : 0;
  
  _cpRenderStats();
  _cpDraw();
}

/* ── Range selector ─────────────────────────────────────────────────────── */
function cpSetRange(btn, range) {
  document.querySelectorAll('.cp-chip[data-range]').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  _cp.range = range;
  _cp.viewportOffset = 0; // reset scroll position on range switch

  // If we already have the full data loaded, just re-slice — no refetch needed
  if (_cp.fullData && _cp.fullData.length) {
    _cp.priceData = _cpSliceByRange(_cp.fullData, range);
    cpUpdateScrollbar();
    // Recompute chg vs first in new window
    const first = _cp.priceData[0];
    const last  = _cp.priceData[_cp.priceData.length - 1];
    _cp.chg     = last ? last.close - first.close : 0;
    _cp.chgPct  = first && first.close ? (_cp.chg / first.close) * 100 : 0;
    _cpRenderStats();
    _cpDraw();
  } else if (_cp.ticker) {
    _cpLoadData();
  }
}

/* ── Astro zone toggle ──────────────────────────────────────────────────── */
function cpToggleAstro(btn) {
  _cp.showAstro = !_cp.showAstro;
  btn.textContent = _cp.showAstro ? 'ZONES ON' : 'ZONES OFF';
  btn.classList.toggle('on', _cp.showAstro);
  if (_cp.priceData.length) _cpDraw();
}

/* ── Drag (mouse) ───────────────────────────────────────────────────────── */
(function() {
  const panel = document.getElementById('chartPanel');
  const bar   = document.getElementById('cpBar');
  if (!panel || !bar) return;

  function toAbsolute() {
    if (panel.style.bottom) {
      const r = panel.getBoundingClientRect();
      panel.style.left   = r.left + 'px';
      panel.style.top    = r.top  + 'px';
      panel.style.right  = 'auto';
      panel.style.bottom = 'auto';
    }
  }

  bar.addEventListener('mousedown', e => {
    if (e.target.closest('button')) return;
    toAbsolute();
    _cp.dragging = true;
    _cp.dStartX  = e.clientX;
    _cp.dStartY  = e.clientY;
    _cp.dStartL  = parseInt(panel.style.left) || 0;
    _cp.dStartT  = parseInt(panel.style.top)  || 0;
    panel.style.boxShadow = '0 28px 90px rgba(0,0,0,.8), 0 0 0 1px var(--accent)';
    panel.style.transition = 'none';
    e.preventDefault();
  });

  window.addEventListener('mousemove', e => {
    if (!_cp.dragging) return;
    const dx = e.clientX - _cp.dStartX;
    const dy = e.clientY - _cp.dStartY;
    panel.style.left = Math.max(0, Math.min(window.innerWidth  - panel.offsetWidth,  _cp.dStartL + dx)) + 'px';
    panel.style.top  = Math.max(0, Math.min(window.innerHeight - panel.offsetHeight, _cp.dStartT + dy)) + 'px';
  });

  window.addEventListener('mouseup', () => {
    if (_cp.dragging) {
      _cp.dragging = false;
      panel.style.boxShadow = '0 20px 70px rgba(0,0,0,.7), 0 0 0 1px rgba(255,255,255,.04)';
      panel.style.transition = 'width .22s ease, height .22s ease';
    }
  });

  // Touch drag
  bar.addEventListener('touchstart', e => {
    if (e.target.closest('button')) return;
    toAbsolute();
    const t = e.touches[0];
    _cp.dragging = true;
    _cp.dStartX  = t.clientX;
    _cp.dStartY  = t.clientY;
    _cp.dStartL  = parseInt(panel.style.left) || 0;
    _cp.dStartT  = parseInt(panel.style.top)  || 0;
  }, { passive: true });

  window.addEventListener('touchmove', e => {
    if (!_cp.dragging) return;
    const t = e.touches[0];
    panel.style.left = Math.max(0, Math.min(window.innerWidth  - panel.offsetWidth,  _cp.dStartL + t.clientX - _cp.dStartX)) + 'px';
    panel.style.top  = Math.max(0, Math.min(window.innerHeight - panel.offsetHeight, _cp.dStartT + t.clientY - _cp.dStartY)) + 'px';
  }, { passive: true });

  window.addEventListener('touchend', () => { _cp.dragging = false; });
})();

/* ── Resize redraw ──────────────────────────────────────────────────────── */
window.addEventListener('resize', () => {
  if (_cp.priceData.length && document.getElementById('chartPanel').style.display !== 'none') {
    _cpDraw();
  }
});
