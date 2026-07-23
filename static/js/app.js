/* ── NSE Composite Screener — app.js ───────────────────────────────────── */
'use strict';

const history = [];
const API_BASE = '/api';
const THEME_KEY = 'theme';

const WEIGHTS = [
  {label:'Fundamentals',  max:30, color:'#00d4aa'},
  {label:'BB Breakout',   max:25, color:'#0099ff'},
  {label:'Volume',        max:15, color:'#f59e0b'},
  {label:'Rel. Strength', max:15, color:'#a855f7'},
  {label:'RSI Momentum',  max:10, color:'#22c55e'},
  {label:'Sector',        max:5,  color:'#ef4444'},
  {label:'Astro Align',   max:5,  color:'#d946ef'},
];

const SCREENER_PRESETS = {
  balanced_daily: {
    label: 'Balanced Daily',
    signal: 'all',
    minScore: 60,
    sortCol: 'total_score',
    sortDir: -1,
    summary: 'Best all-round positional ideas with quality and trend alignment.',
    chips: ['Score >= 60', 'All signals', 'Default market sweep'],
    insights: [
      {title: 'Quality first', body: 'Rewards companies that are clearing the hard filters while still carrying decent growth and profitability metrics.'},
      {title: 'Trend confirmation', body: 'Favors stocks already above key moving averages so the report stays cleaner and less noisy.'},
      {title: 'Swing-ready basket', body: 'Useful when you want a broad shortlist before doing manual chart review on Angel One.'},
    ],
  },
  breakout_volume: {
    label: 'Breakout + Volume',
    signal: 'breakout',
    minScore: 65,
    sortCol: 'volume_ratio',
    sortDir: -1,
    summary: 'Focus on BB breakouts backed by strong participation.',
    chips: ['Breakout only', 'Min score 65', 'Sort by volume'],
    insights: [
      {title: 'Expansion move', body: 'Looks for stocks where price has already started expanding beyond the squeeze zone.'},
      {title: 'Participation check', body: 'Volume gets priority here so weak breakouts do not float to the top.'},
      {title: 'Execution fit', body: 'Best when you want the report to surface names that deserve immediate chart follow-up.'},
    ],
  },
  quality_growth: {
    label: 'Quality Growth',
    signal: 'buy',
    minScore: 70,
    sortCol: 'roe_pct',
    sortDir: -1,
    summary: 'Higher-grade names with cleaner fundamentals and strong returns on capital.',
    chips: ['BUY grades', 'Min score 70', 'Sort by ROE'],
    insights: [
      {title: 'Capital efficiency', body: 'Leans into ROE and ROCE so capital-light compounders rise quickly.'},
      {title: 'Cleaner balance sheet', body: 'Works well for users who want stronger business quality before momentum.'},
      {title: 'Portfolio shortlist', body: 'Ideal when the screener is being used more like a swing-investing watchlist builder.'},
    ],
  },
  squeeze_watch: {
    label: 'Squeeze Watch',
    signal: 'squeeze',
    minScore: 55,
    sortCol: 'bb_squeeze_pct',
    sortDir: 1,
    summary: 'Tight daily ranges that could be setting up for the next expansion leg.',
    chips: ['Squeeze only', 'Min score 55', 'Tightest bands first'],
    insights: [
      {title: 'Compression focus', body: 'Surfaces low-bandwidth names before the actual breakout starts showing up.'},
      {title: 'Patience setup', body: 'Useful when you prefer watchlist preparation over chasing already-extended candles.'},
      {title: 'Daily chart discipline', body: 'Pairs especially well with your 1D-candle approach because the setups are calmer and more readable.'},
    ],
  },
};

/* Full Nifty 50 universe with sectors */
const NIFTY50 = [
  {ticker:'RELIANCE',   sector:'Energy'},
  {ticker:'TCS',        sector:'Technology'},
  {ticker:'HDFCBANK',   sector:'Banking'},
  {ticker:'INFY',       sector:'Technology'},
  {ticker:'ICICIBANK',  sector:'Banking'},
  {ticker:'HINDUNILVR', sector:'Consumer'},
  {ticker:'ITC',        sector:'Consumer'},
  {ticker:'SBIN',       sector:'Banking'},
  {ticker:'BHARTIARTL', sector:'Telecom'},
  {ticker:'KOTAKBANK',  sector:'Banking'},
  {ticker:'LT',         sector:'Capital Goods'},
  {ticker:'HCLTECH',    sector:'Technology'},
  {ticker:'AXISBANK',   sector:'Banking'},
  {ticker:'BAJFINANCE', sector:'Financial'},
  {ticker:'WIPRO',      sector:'Technology'},
  {ticker:'MARUTI',     sector:'Automobile'},
  {ticker:'SUNPHARMA',  sector:'Pharma'},
  {ticker:'TITAN',      sector:'Consumer'},
  {ticker:'ULTRACEMCO', sector:'Cement'},
  {ticker:'ASIANPAINT', sector:'Consumer'},
  {ticker:'NESTLEIND',  sector:'Consumer'},
  {ticker:'POWERGRID',  sector:'Energy'},
  {ticker:'NTPC',       sector:'Energy'},
  {ticker:'ONGC',       sector:'Oil & Gas'},
  {ticker:'JSWSTEEL',   sector:'Metals'},
  {ticker:'TATAMOTORS', sector:'Automobile'},
  {ticker:'M&M',        sector:'Automobile'},
  {ticker:'TECHM',      sector:'Technology'},
  {ticker:'INDUSINDBK', sector:'Banking'},
  {ticker:'ADANIENT',   sector:'Conglomerate'},
  {ticker:'BAJAJFINSV', sector:'Financial'},
  {ticker:'GRASIM',     sector:'Cement'},
  {ticker:'ADANIPORTS', sector:'Infrastructure'},
  {ticker:'COALINDIA',  sector:'Energy'},
  {ticker:'BPCL',       sector:'Oil & Gas'},
  {ticker:'CIPLA',      sector:'Pharma'},
  {ticker:'DRREDDY',    sector:'Pharma'},
  {ticker:'EICHERMOT',  sector:'Automobile'},
  {ticker:'HEROMOTOCO', sector:'Automobile'},
  {ticker:'HINDALCO',   sector:'Metals'},
  {ticker:'TATASTEEL',  sector:'Metals'},
  {ticker:'SBILIFE',    sector:'Insurance'},
  {ticker:'HDFCLIFE',   sector:'Insurance'},
  {ticker:'BRITANNIA',  sector:'Consumer'},
  {ticker:'DIVISLAB',   sector:'Pharma'},
  {ticker:'APOLLOHOSP', sector:'Healthcare'},
  {ticker:'TATACONSUM', sector:'Consumer'},
  {ticker:'BAJAJ-AUTO', sector:'Automobile'},
  {ticker:'UPL',        sector:'Chemicals'},
  {ticker:'SHREECEM',   sector:'Cement'},
];

const SECTOR_MAP = {
  'Capital Goods':1,'Defence':1,'Engineering':1,
  'Banking':2,'Financial Services':2,'Financial':2,
  'Pharmaceuticals':3,'Healthcare':3,'Pharma':3,
  'Technology':4,'IT':4,'Information Technology':4,
  'Automobile':5,'Auto':5,'Consumer':6,
  'Energy':7,'Oil':7,'Metals':8,'Real Estate':9,
};

/* ── Weights panel ─────────────────────────────────────────────────────── */
/**
 * @param {number[]|null} actual  - actual scored values [fund, bb, vol, rs, rsi, sector]
 *                                  if null, shows max (initial/reset state)
 */
function renderWeights(actual = null) {
  document.getElementById('weights-display').innerHTML = WEIGHTS.map((w, i) => {
    const val     = actual ? (actual[i] ?? 0) : w.max;
    const barPct  = Math.min(100, (val / w.max) * 100);
    const valHtml = actual
      ? `<span class="weight-val" style="color:${w.color}">${val}<span style="color:var(--text3);font-size:9px">/${w.max}</span></span>`
      : `<span class="weight-val">${w.max}</span>`;
    return `
    <div class="weight-row">
      <span class="weight-label">${w.label}</span>
      <div class="weight-bar-wrap"><div class="weight-bar-fill" style="width:${barPct}%;background:${w.color};transition:width .6s cubic-bezier(.16,1,.3,1)"></div></div>
      ${valHtml}
    </div>`;
  }).join('');
}

function applyTheme(theme) {
  const resolvedTheme = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', resolvedTheme);
  localStorage.setItem(THEME_KEY, resolvedTheme);

  const toggle = document.getElementById('themeToggle');
  if (toggle) {
    toggle.checked = resolvedTheme === 'dark';
  }
}

function initThemeToggle() {
  const toggle = document.getElementById('themeToggle');
  if (!toggle) return;

  const savedTheme = localStorage.getItem(THEME_KEY) || 'dark';
  applyTheme(savedTheme);

  toggle.addEventListener('change', e => {
    applyTheme(e.target.checked ? 'dark' : 'light');
  });
}

/* ── Clock ─────────────────────────────────────────────────────────────── */
function updateClock() {
  const ist = new Date(new Date().toLocaleString('en-US', {timeZone:'Asia/Kolkata'}));
  document.getElementById('clock').textContent = ist.toTimeString().slice(0,8) + ' IST';
}
setInterval(updateClock, 1000);
updateClock();
renderWeights();

/* ── Scoring helpers ───────────────────────────────────────────────────── */
function sectorScore(sector='') {
  for (const [k, rank] of Object.entries(SECTOR_MAP)) {
    if (sector.toLowerCase().includes(k.toLowerCase()))
      return {rank, score: Math.max(0, 5-(rank-1))};
  }
  return {rank:10, score:1};
}

function scoreFundamentals(h={}, bs={}) {
  const roe=+h.ReturnOnEquityTTM||0, pm=+h.ProfitMargin||0, opm=+h.OperatingMarginTTM||0;
  const rg=+h.QuarterlyRevenueGrowthYOY||0, eg=+h.QuarterlyEarningsGrowthYOY||0;
  const debt=+bs.totalDebt||0, eq=+bs.totalStockholderEquity||1;
  const de = eq>0 ? debt/eq : null;

  let roe_s=0, margin_s=0, growth_s=0, debt_s=3;
  if(roe>0.25)roe_s=8; else if(roe>0.20)roe_s=7; else if(roe>0.15)roe_s=5; else if(roe>0.10)roe_s=3; else if(roe>0)roe_s=1;
  let np=0,op=0;
  if(pm>0.20)np=4; else if(pm>0.12)np=3; else if(pm>0.06)np=2; else if(pm>0)np=1;
  if(opm>0.20)op=3; else if(opm>0.12)op=2; else if(opm>0.06)op=1;
  margin_s = Math.min(7, np+op);
  let rp=0,ep=0;
  if(rg>0.25)rp=4; else if(rg>0.15)rp=3; else if(rg>0.08)rp=2; else if(rg>0.02)rp=1;
  if(eg>0.25)ep=4; else if(eg>0.15)ep=3; else if(eg>0.08)ep=2; else if(eg>0)ep=1;
  growth_s = Math.min(8, rp+ep);
  if(de!==null){if(de<0.1)debt_s=7; else if(de<0.3)debt_s=6; else if(de<0.5)debt_s=5; else if(de<0.8)debt_s=3; else if(de<1.5)debt_s=1; else debt_s=0;}

  return {total:roe_s+margin_s+growth_s+debt_s, roe_s, margin_s, growth_s, debt_s, raw:{roe,pm,opm,rg,eg,de}};
}

function scoreTechnicals(priceData=[]) {
  if (!priceData || priceData.length < 70) return {total:0, bb_s:0, vol_s:0, rs_s:7, rsi_s:0};
  const closes  = priceData.map(d => +d.adjusted_close || +d.close || 0);
  const volumes = priceData.map(d => +d.volume || 0);
  const n = closes.length;

  const mean   = arr => arr.reduce((a,b)=>a+b,0)/arr.length;
  const stddev = arr => { const m=mean(arr); return Math.sqrt(arr.reduce((a,b)=>a+(b-m)**2,0)/arr.length); };

  const bws=[];
  for(let i=20;i<n;i++){
    const sl=closes.slice(i-20,i), m=mean(sl), s=stddev(sl);
    bws.push(m>0?(4*s/m)*100:0);
  }
  const curBW=bws[bws.length-1], hist63=bws.slice(-63);
  const bwMin=Math.min(...hist63), bwMax=Math.max(...hist63);
  const bwPct = bwMax>bwMin ? ((curBW-bwMin)/(bwMax-bwMin))*100 : 50;
  let bb_s=0;
  if(bwPct<=10)bb_s=25; else if(bwPct<=20)bb_s=20; else if(bwPct<=35)bb_s=13; else if(bwPct<=50)bb_s=6;

  let ema50=closes[0];
  for(let i=1;i<n;i++) ema50=ema50*(49/51)+closes[i]*(2/51);
  if(closes[n-1]<ema50) bb_s=Math.max(0,bb_s-5);

  const avgVol20 = mean(volumes.slice(-21,-1));
  const volRatio = avgVol20>0 ? volumes[n-1]/avgVol20 : 1;
  let vol_s=0;
  if(volRatio>=3)vol_s=15; else if(volRatio>=2)vol_s=12; else if(volRatio>=1.5)vol_s=8; else if(volRatio>=1)vol_s=4;

  const deltas=closes.slice(1).map((c,i)=>c-closes[i]);
  const gains=deltas.map(d=>d>0?d:0), losses=deltas.map(d=>d<0?-d:0);
  const avgG=mean(gains.slice(-14)), avgL=mean(losses.slice(-14));
  const rsi = avgL===0 ? 100 : 100-(100/(1+(avgG/avgL)));
  let rsi_s=0;
  if(rsi>=55&&rsi<=68)rsi_s=10; else if(rsi>=50&&rsi<55)rsi_s=7; else if(rsi>68&&rsi<=75)rsi_s=5; else if(rsi>=40)rsi_s=3;

  return {
    total: bb_s+vol_s+7+rsi_s, bb_s, vol_s, rs_s:7, rsi_s,
    raw: {bwPct:bwPct.toFixed(1), volRatio:volRatio.toFixed(2), rsi:rsi.toFixed(1), ema50:ema50.toFixed(2), curClose:closes[n-1], aboveEma:closes[n-1]>ema50}
  };
}

function gradeScore(sc) {
  if(sc>=80) return {grade:'A+', signal:'STRONG BUY', cls:'pill-buy'};
  if(sc>=70) return {grade:'A',  signal:'BUY',        cls:'pill-buy'};
  if(sc>=60) return {grade:'B',  signal:'WATCH',      cls:'pill-watch'};
  if(sc>=45) return {grade:'C',  signal:'NEUTRAL',    cls:'pill-neutral'};
  return             {grade:'D',  signal:'SKIP',       cls:'pill-skip'};
}

function scoreColor(sc) {
  if(sc>=70) return '#00d4aa';
  if(sc>=55) return '#f59e0b';
  return '#ef4444';
}

function pct(v,max) { return Math.min(100,(v/max)*100).toFixed(1); }
function fmt(v,d=2) { return v==null||isNaN(v)?'—':Number(v).toFixed(d); }
function fmtP(v)    { return v==null||isNaN(v)?'—':(v*100).toFixed(1)+'%'; }
function fmtCr(v)   {
  if(!v||isNaN(v)) return '—';
  const cr=v/1e7;
  return cr>=1e5?'₹'+(cr/1e5).toFixed(1)+'L Cr':cr>=1000?'₹'+(cr/1000).toFixed(1)+'K Cr':'₹'+cr.toFixed(0)+' Cr';
}

/* ── Actions ───────────────────────────────────────────────────────────── */
function loadTicker(t) {
  document.getElementById('tickerInput').value = t;
  fetchStock();
}

function clearView() {
  document.getElementById('resultView').style.display = 'none';
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('tickerInput').value = '';
  renderWeights(); // reset sidebar to max values
}

/* ── Dynamic Quick-Load Dropdown ─────────────────────────────────────────── */

// _activeUniverse: flat list of {ticker, sector, index} fetched from /api/universe
let _activeUniverse = NIFTY50.map(s => ({ ...s, index: 'nifty50' }));
let _activeTotalCount = 50;

const _INDEX_LABEL = {
  nifty50:   'Nifty 50',
  next50:    'Nifty Next 50',
  midcap100: 'Midcap 100',
  smallcap250: 'Nifty Smallcap 250',
  midsmallcap400: 'Nifty MidSmallcap 400',
  nifty500_custom: 'Nifty 500 Extended',
  nifty500:  'Nifty 500 Extended',
  all:       'All Stocks',
};

// Fetch universe from backend for the given index param string (e.g. "nifty50,next50")
async function loadUniverse(indexParam) {
  try {
    const data = await fetch(`${API_BASE}/universe?index=${encodeURIComponent(indexParam)}`).then(r => r.json());
    _activeUniverse   = data.combined || [];
    _activeTotalCount = data.total    || _activeUniverse.length;

    // Build human-readable label from selected indices
    const parts  = indexParam.split(',').map(p => p.trim());
    const labels = parts.map(p => _INDEX_LABEL[p] || p).join(' + ');
    document.getElementById('quickLoadLabel').textContent  = `Quick Load — ${labels}`;
    document.getElementById('indexCountBadge').textContent = `${_activeTotalCount} stocks`;
    document.getElementById('indexFooter').textContent     = `${_activeTotalCount} / ${_activeTotalCount} stocks`;
    document.getElementById('indexSearch').value = '';
    // Rebuild list if panel is open
    if (document.getElementById('indexPanel').classList.contains('open')) {
      buildIndexList(_activeUniverse, data.groups || {});
    }
  } catch(e) {
    console.warn('Universe load failed:', e);
  }
}

// Build the visible list — supports grouped rendering when groups dict is provided
function buildIndexList(items = _activeUniverse, groups = {}) {
  const el = document.getElementById('indexList');
  if (!items.length) {
    el.innerHTML = '<div class="index-no-results">NO MATCH FOUND</div>';
    document.getElementById('indexFooter').textContent = `0 / ${_activeTotalCount} stocks`;
    return;
  }

  const useGroups = Object.keys(groups).length > 0 &&
                    items === _activeUniverse;  // only group when showing full unfiltered list

  if (useGroups) {
    // Render with group header separators
    let html = '';
    const groupKeys = Object.keys(groups);
    groupKeys.forEach(gk => {
      const gItems = groups[gk];
      if (!gItems || !gItems.length) return;
      html += `<div class="index-group-header">${_INDEX_LABEL[gk] || gk} <span>${gItems.length}</span></div>`;
      html += gItems.map(s => `
        <div class="index-item" onclick="selectIndex('${s.ticker}')">
          <span class="index-item-ticker">${s.ticker}</span>
          <span class="index-item-sector">${s.sector}</span>
        </div>`).join('');
    });
    el.innerHTML = html;
  } else {
    // Flat list (search results)
    el.innerHTML = items.map(s => `
      <div class="index-item" onclick="selectIndex('${s.ticker}')">
        <span class="index-item-ticker">${s.ticker}</span>
        <span class="index-item-sector">${s.sector}</span>
      </div>`).join('');
  }

  document.getElementById('indexFooter').textContent =
    `${items.length} / ${_activeTotalCount} stocks`;
}

// Internal: last fetched groups (for re-render with groups on open)
let _lastGroups = {};

async function _refreshDropdown(indexParam) {
  try {
    const data = await fetch(`${API_BASE}/universe?index=${encodeURIComponent(indexParam)}`).then(r => r.json());
    _activeUniverse   = data.combined || [];
    _activeTotalCount = data.total    || _activeUniverse.length;
    _lastGroups       = data.groups   || {};

    const parts  = indexParam.split(',').map(p => p.trim());
    const labels = parts.map(p => _INDEX_LABEL[p] || p).join(' + ');
    document.getElementById('quickLoadLabel').textContent  = `Quick Load — ${labels}`;
    document.getElementById('indexCountBadge').textContent = `${_activeTotalCount} stocks`;

    if (document.getElementById('indexPanel').classList.contains('open')) {
      buildIndexList(_activeUniverse, _lastGroups);
    }
    renderScreenerTable();
  } catch(e) { console.warn('Universe refresh failed:', e); }
}

function toggleDropdown() {
  const trigger = document.getElementById('indexTrigger');
  const panel   = document.getElementById('indexPanel');
  const isOpen  = panel.classList.contains('open');
  if (isOpen) {
    closeDropdown();
  } else {
    panel.classList.add('open');
    trigger.classList.add('open');
    buildIndexList(_activeUniverse, _lastGroups);
    setTimeout(() => document.getElementById('indexSearch').focus(), 50);
  }
}

function closeDropdown() {
  document.getElementById('indexPanel').classList.remove('open');
  document.getElementById('indexTrigger').classList.remove('open');
  document.getElementById('indexSearch').value = '';
}

function filterIndex() {
  const q = document.getElementById('indexSearch').value.trim().toLowerCase();
  const filtered = q
    ? _activeUniverse.filter(s =>
        s.ticker.toLowerCase().includes(q) ||
        s.sector.toLowerCase().includes(q))
    : _activeUniverse;
  // Pass empty groups dict so we always show flat list when searching
  buildIndexList(filtered, q ? {} : _lastGroups);
}

function selectIndex(ticker) {
  document.getElementById('indexTriggerText').textContent = ticker;
  closeDropdown();
  loadTicker(ticker);
}

// Close dropdown when clicking outside
document.addEventListener('click', e => {
  const dd = document.getElementById('indexDropdown');
  if (dd && !dd.contains(e.target)) closeDropdown();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeDropdown();
});

// ── Initialise: fetch universe for default (Nifty 50) on page load ────────
(async () => {
  try {
    const data = await fetch(`${API_BASE}/universe?index=nifty50`).then(r => r.json());
    _activeUniverse   = data.combined || NIFTY50.map(s => ({ ...s, index: 'nifty50' }));
    _activeTotalCount = data.total    || 50;
    _lastGroups       = data.groups   || {};
    document.getElementById('indexFooter').textContent = `${_activeTotalCount} / ${_activeTotalCount} stocks`;
  } catch(e) {
    // Fallback to hardcoded list silently
    _lastGroups = { nifty50: _activeUniverse };
  }
})();


/* ── Fetch ─────────────────────────────────────────────────────────────── */
async function fetchStock() {
  const rawTicker = document.getElementById('tickerInput').value.trim().toUpperCase();
  if (!rawTicker) return;
  const ticker = rawTicker.replace('.NSE','').replace('.NS','');

  document.getElementById('emptyState').style.display    = 'none';
  document.getElementById('resultView').style.display    = 'none';
  document.getElementById('loadingState').style.display  = 'flex';
  document.getElementById('fetchBtn').disabled = true;

  const steps = ['CONNECTING TO LOCAL BACKEND...','FETCHING FUNDAMENTALS...','LOADING PRICE HISTORY...','COMPUTING SCORES...'];
  let si = 0;
  const interval = setInterval(() => {
    document.getElementById('loaderText').textContent = steps[si%steps.length]; si++;
  }, 800);

  try {
    const res     = await fetch(`${API_BASE}/stock?ticker=${encodeURIComponent(ticker)}`);
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.error || `Backend error ${res.status}`);

    const fund      = payload.fundamentals;
    const priceData = Array.isArray(payload.price_data) ? payload.price_data : [];
    const composite = payload.composite || null;
    const ltpInfo   = payload.ltp || null;    // {value, source} from Angel One
    if (!fund || !fund.General) throw new Error('No data returned. Verify the NSE ticker symbol.');

    clearInterval(interval);
    renderResult(ticker, fund, priceData, composite, ltpInfo);
  } catch(e) {
    clearInterval(interval);
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('resultView').innerHTML = `
      <div class="error-box" style="position:relative;padding-right:32px">
        <button onclick="clearView()" class="close-btn-error" title="Close">✕</button>
        ⚠ ${e.message}
      </div>`;
    document.getElementById('resultView').style.display = 'block';
  } finally {
    document.getElementById('fetchBtn').disabled = false;
  }
}

/* ── Render ──────────────────────────────────────────────────────── */
function renderResult(ticker, fund, priceData, composite=null, ltpInfo=null) {
  const h   = fund.Highlights || {};
  const g   = fund.General    || {};
  const val = fund.Valuation  || {};
  const bsQ = fund.Financials?.Balance_Sheet?.quarterly || {};
  const latQ = Object.keys(bsQ).sort().reverse()[0];
  const bs   = latQ ? bsQ[latQ] : {};

  const fallbackFundSc = scoreFundamentals(h, bs);
  const fallbackTechSc = scoreTechnicals(priceData);
  const fallbackSecSc  = sectorScore(g.Sector || '');

  const fundSc = composite?.fundamental ? {
    total: composite.fundamental.total ?? fallbackFundSc.total,
    raw:   { de: composite.fundamental.debt_equity ?? fallbackFundSc.raw.de },
  } : fallbackFundSc;

  const techSc = composite?.technical ? {
    total: composite.technical.total ?? fallbackTechSc.total,
    raw: {
      bwPct:      composite.technical.bandwidth_pct ?? fallbackTechSc.raw?.bwPct,
      volRatio:   composite.technical.vol_ratio     ?? fallbackTechSc.raw?.volRatio,
      rsi:        composite.technical.rsi           ?? fallbackTechSc.raw?.rsi,
      curClose:   composite.technical.close         ?? fallbackTechSc.raw?.curClose,
      aboveEma:   composite.technical.above_ema50   ?? fallbackTechSc.raw?.aboveEma,
      rsRatio:    composite.technical.rs_ratio      ?? fallbackTechSc.raw?.rsRatio,
      adx:        composite.technical.adx,
      atr:        composite.technical.atr,
      aboveEma200: composite.technical.above_ema200,
      goldenCross: composite.technical.golden_cross,
      stopLoss:   composite.technical.stop_loss,
      adxScore:   composite.technical.adx_score,
    }
  } : fallbackTechSc;

  const secSc = composite?.sector_sc ? {
    score: composite.sector_sc.sector_score ?? fallbackSecSc.score,
    rank:  composite.sector_sc.sector_rank  ?? fallbackSecSc.rank,
  } : fallbackSecSc;

  const astroSc = composite?.astro_sc ? {
    score:   composite.astro_sc.astro_score ?? 3.0,
    planets: composite.astro_sc.ruling_planets ?? 'Jup',
    status:  composite.astro_sc.transit_status ?? 'Neutral'
  } : { score: 3.0, planets: 'Jup', status: 'Neutral' };

  const total   = composite?.total ?? Math.min(100, Math.round(fundSc.total + techSc.total + secSc.score + astroSc.score));
  const gObj    = gradeScore(total);
  const grade   = composite?.grade  || gObj.grade;
  const signal  = (composite?.signal || gObj.signal).toUpperCase();
  const cls     = signal.includes('BUY') ? 'pill-buy' : signal==='WATCH' ? 'pill-watch' : signal==='NEUTRAL' ? 'pill-neutral' : 'pill-skip';
  const sColor  = scoreColor(total);

  const r=36, cx=45, cy=45, circ=2*Math.PI*r;
  const arc = `M ${cx} ${cy-r} A ${r} ${r} 0 ${total>50?1:0} 1 ${cx+r*Math.sin(2*Math.PI*total/100)} ${cy-r*Math.cos(2*Math.PI*total/100)}`;

  addHistory(ticker, total, sColor);

  // Prefer Angel One real-time LTP over yfinance close
  const angelLtp  = ltpInfo?.value ?? null;
  const ltpSource = ltpInfo?.source || 'yfinance';
  const close     = angelLtp || +techSc.raw?.curClose || 0;
  const closeDisp = close > 0 ? '₹'+close.toFixed(2) : '—';
  const de        = fundSc.raw?.de;

  document.getElementById('loadingState').style.display = 'none';
  document.getElementById('resultView').innerHTML = `
  <div class="score-hero" style="position:relative">
    <button onclick="clearView()" class="close-btn" title="Close details">✕</button>
    <div class="score-ring">
      <svg width="90" height="90" viewBox="0 0 90 90">
        <circle cx="45" cy="45" r="36" fill="none" stroke="#1d2433" stroke-width="6"/>
        <path d="${arc}" fill="none" stroke="${sColor}" stroke-width="6" stroke-linecap="round"/>
      </svg>
      <div class="score-ring-val">
        <div class="score-num" style="color:${sColor}">${total}</div>
        <div class="score-grade" style="color:${sColor}">${grade}</div>
      </div>
    </div>
    <div>
      <div class="stock-name">${g.Name||ticker}</div>
      <div class="stock-meta">${ticker}.NSE · ${g.Sector||'—'} · ${g.Industry||'—'} · ${g.CurrencyCode||'INR'}</div>
      <span class="signal-pill ${cls}">● ${signal}</span>
    </div>
    <div style="padding-top: 12px;">
      <div class="close-label">LTP / CLOSE</div>
      <div class="close-price">${closeDisp}</div>
    </div>
  </div>

  <div class="sub-scores">
    <div class="sub-card">
      <div class="sub-label">Fundamentals</div>
      <div class="sub-value" style="color:#00d4aa">${fundSc.total}<span class="sub-max"> /30</span></div>
      <div class="sub-bar"><div class="sub-bar-fill" style="width:${pct(fundSc.total,30)}%;background:#00d4aa"></div></div>
    </div>
    <div class="sub-card">
      <div class="sub-label">BB + Technical</div>
      <div class="sub-value" style="color:#0099ff">${techSc.total}<span class="sub-max"> /65</span></div>
      <div class="sub-bar"><div class="sub-bar-fill" style="width:${pct(techSc.total,65)}%;background:#0099ff"></div></div>
    </div>
    <div class="sub-card">
      <div class="sub-label">Sector Bonus</div>
      <div class="sub-value" style="color:#a855f7">${secSc.score}<span class="sub-max"> /5</span></div>
      <div class="sub-bar"><div class="sub-bar-fill" style="width:${pct(secSc.score,5)}%;background:#a855f7"></div></div>
    </div>
    <div class="sub-card" style="border-right: 1px solid rgba(217, 70, 239, 0.15)">
      <div class="sub-label">Astro Align (${astroSc.planets})</div>
      <div class="sub-value" style="color:${astroSc.status==='Upside'?'#00d4aa':astroSc.status==='Downside'?'#ef4444':'#f59e0b'}">${astroSc.score}<span class="sub-max"> /5</span></div>
      <div class="sub-bar"><div class="sub-bar-fill" style="width:${pct(astroSc.score,5)}%;background:${astroSc.status==='Upside'?'#00d4aa':astroSc.status==='Downside'?'#ef4444':'#f59e0b'}"></div></div>
    </div>
    <div class="sub-card" style="display:none">
      <div class="sub-label">BB Squeeze %</div>
      <div class="sub-value" style="color:${+techSc.raw?.bwPct<25?'#22c55e':'#f59e0b'}">${techSc.raw?.bwPct||'—'}<span class="sub-max"> pct</span></div>
      <div class="sub-bar"><div class="sub-bar-fill" style="width:${100-(+techSc.raw?.bwPct||50)}%;background:${+techSc.raw?.bwPct<25?'#22c55e':'#f59e0b'}"></div></div>
    </div>
  </div>

  <div class="tables-grid">
    <div class="table-card">
      <div class="table-head"><div class="table-head-title">◈ Profitability</div></div>
      <table class="tbl">
        ${tRow('ROE',           fmtP(h.ReturnOnEquityTTM),        h.ReturnOnEquityTTM>0.15?'PASS':'FAIL')}
        ${tRow('Net Margin',    fmtP(h.ProfitMargin),             h.ProfitMargin>0.08?'PASS':'FAIL')}
        ${tRow('Op. Margin',    fmtP(h.OperatingMarginTTM),       h.OperatingMarginTTM>0.10?'PASS':'WARN')}
        ${tRow('ROA',           fmtP(h.ReturnOnAssetsTTM),        h.ReturnOnAssetsTTM>0.06?'PASS':'FAIL')}
        ${tRow('EBITDA Margin', '—',                               'WARN')}
      </table>
    </div>
    <div class="table-card">
      <div class="table-head"><div class="table-head-title">◈ Valuation</div></div>
      <table class="tbl">
        ${tRow('Trailing PE', fmt(val.TrailingPE||h.PERatio,1), val.TrailingPE>0&&val.TrailingPE<35?'PASS':'WARN')}
        ${tRow('Forward PE',  fmt(val.ForwardPE,1),             val.ForwardPE>0&&val.ForwardPE<30?'PASS':'WARN')}
        ${tRow('PEG Ratio',   fmt(h.PEGRatio,2),                h.PEGRatio<1.5?'PASS':'WARN')}
        ${tRow('P/Book',      fmt(val.PriceBookMRQ,2),          'WARN')}
        ${tRow('EV/EBITDA',   fmt(val.EnterpriseValueEbitda,1), val.EnterpriseValueEbitda<15?'PASS':'WARN')}
      </table>
    </div>
    <div class="table-card">
      <div class="table-head"><div class="table-head-title">◈ Growth</div></div>
      <table class="tbl">
        ${tRow('Rev Growth (YoY)',  fmtP(h.QuarterlyRevenueGrowthYOY),  h.QuarterlyRevenueGrowthYOY>0.08?'PASS':'FAIL')}
        ${tRow('EPS Growth (YoY)', fmtP(h.QuarterlyEarningsGrowthYOY), h.QuarterlyEarningsGrowthYOY>0.08?'PASS':'FAIL')}
        ${tRow('EPS TTM',          '₹'+fmt(h.DilutedEpsTTM,1),         'WARN')}
        ${tRow('EPS Est. CY',      '₹'+fmt(h.EPSEstimateCurrentYear,1), 'WARN')}
        ${tRow('EPS Est. NY',      '₹'+fmt(h.EPSEstimateNextYear,1),    h.EPSEstimateNextYear>h.EPSEstimateCurrentYear?'PASS':'FAIL')}
      </table>
    </div>
    <div class="table-card">
      <div class="table-head"><div class="table-head-title">◈ Financial Health</div></div>
      <table class="tbl">
        ${tRow('Debt / Equity', de!=null?fmt(de,2):'—',           de!=null?de<0.5?'PASS':de<1?'WARN':'FAIL':'WARN')}
        ${tRow('RSI (14)',      techSc.raw?.rsi||'—',             techSc.raw?.rsi>=55&&techSc.raw?.rsi<=68?'PASS':techSc.raw?.rsi>75?'FAIL':'WARN')}
        ${tRow('Sector Rank',  '#'+secSc.rank+' — '+(g.Sector||'—'), secSc.rank<=3?'PASS':secSc.rank<=6?'WARN':'FAIL')}
      </table>
    </div>
  </div>

  <div class="verdict-card">
    <div class="table-head"><div class="table-head-title">◈ Screener Verdict — BB Squeeze Pre-Earnings Candidate</div></div>
    <div class="verdict-grid">
      ${vItem('RSI Zone',          techSc.raw?.rsi>=55&&techSc.raw?.rsi<=68?'IDEAL (55-68)':'OUTSIDE ZONE', techSc.raw?.rsi>=55&&techSc.raw?.rsi<=68)}
      ${vItem('Fundamental Quality', fundSc.total>=20?'STRONG':'WEAK',               fundSc.total>=20)}
      ${vItem('Sector Strength',   secSc.rank<=4?'TOP SECTOR':'NEUTRAL',             secSc.rank<=4)}
    </div>
  </div>`;

  document.getElementById('resultView').style.display = 'block';

  // ── Update sidebar Score Weights with actual scored points ──────────────
  const bbScore  = composite?.technical?.bb_score     ?? 0;
  const volScore = composite?.technical?.volume_score ?? 0;
  const rsScore  = composite?.technical?.rs_score     ?? 0;
  const rsiScore = composite?.technical?.rsi_score    ?? 0;
  renderWeights([fundSc.total, bbScore, volScore, rsScore, rsiScore, secSc.score, astroSc.score]);
}

/* ── Row helpers ───────────────────────────────────────────────────────── */
function tRow(label, val, status) {
  const cls = status==='PASS'?'badge-pass':status==='FAIL'?'badge-fail':'badge-warn';
  return `<tr>
    <td class="td-label">${label}</td>
    <td class="td-val">${val}</td>
    <td class="td-badge"><span class="badge ${cls}">${status}</span></td>
  </tr>`;
}

function vItem(label, val, pass) {
  return `<div class="verdict-item">
    <div class="verdict-check">${label}</div>
    <div class="verdict-val" style="color:${pass?'var(--accent)':'var(--red)'}">${val}</div>
  </div>`;
}

/* ── History ───────────────────────────────────────────────────────────── */
function addHistory(ticker, score, color) {
  history.unshift({ticker, score, color});
  if (history.length > 8) history.pop();
  const el  = document.getElementById('history-list');
  const sec = document.getElementById('history-section');
  sec.style.display = 'block';
  el.innerHTML = history.map(h => `
    <div class="history-item" onclick="loadTicker('${h.ticker}')">
      <span class="history-ticker">${h.ticker}</span>
      <span class="history-score" style="color:${h.color}">${h.score}</span>
    </div>`).join('');
}

/* ── Keyboard shortcut ─────────────────────────────────────────────────── */
document.getElementById('tickerInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') fetchStock();
});

/* ── Tab switching ──────────────────────────────────────────────────────── */
function switchTab(tab) {
  // Update tab nav buttons (new tab-nav structure)
  ['screener','sectors'].forEach(t => {
    const btn = document.getElementById(`tab-${t}`);
    if (btn) btn.classList.toggle('active', t === tab);
  });

  const isScreener = tab === 'screener';
  const isSectors  = tab === 'sectors';

  // Show/hide main panels
  document.getElementById('screenerView').style.display = isScreener ? 'block' : 'none';
  document.getElementById('sectorView').style.display   = isSectors  ? 'block' : 'none';

  // Stock detail view — preserve across tab switches
  const rv = document.getElementById('resultView');
  if (rv) {
    if (isScreener) {
      rv.style.display = rv.dataset.prevDisplay || 'none';
    } else {
      rv.dataset.prevDisplay = rv.style.display;
      rv.style.display = 'none';
    }
  }

  if (isSectors) {
    loadSectorData();
  }
}

/* ── Batch Screener ─────────────────────────────────────────────────────── */
let _screenerData = [];
let _sortCol      = 'total_score';
let _sortDir      = -1;
let _activePreset = 'quality_growth';
let _screenerMode = 'new'; // 'new' | 'running' | 'booked'

function _currentPreset() {
  return SCREENER_PRESETS[_activePreset] || SCREENER_PRESETS.balanced_daily;
}

function initScreenerPresets() {
  const select = document.getElementById('screenerPreset');
  if (!select) return;

  select.innerHTML = Object.entries(SCREENER_PRESETS).map(([key, preset]) =>
    `<option value="${key}">${preset.label}</option>`
  ).join('');

  renderPresetStrip();
  applyScreenerPreset(_activePreset, false);
}

function renderPresetStrip() {
  const wrap = document.getElementById('presetStrip');
  if (!wrap) return;

  wrap.innerHTML = Object.entries(SCREENER_PRESETS).map(([key, preset]) => `
    <button type="button" class="preset-card${key === _activePreset ? ' active' : ''}" onclick="applyScreenerPreset('${key}')">
      <div class="preset-card-title">${preset.label}</div>
      <div class="preset-card-copy">${preset.summary}</div>
      <div class="preset-card-meta">
        ${preset.chips.map(chip => `<span class="preset-chip">${chip}</span>`).join('')}
      </div>
    </button>
  `).join('');
}

function renderInsightPanel() {
  const panel = document.getElementById('insightPanel');
  const grid = document.getElementById('insightGrid');
  const tag = document.getElementById('insightPresetTag');
  if (!panel || !grid || !tag) return;

  const preset = _currentPreset();
  tag.textContent = preset.label;
  grid.innerHTML = preset.insights.map(item => `
    <div class="insight-card">
      <h3>${item.title}</h3>
      <p>${item.body}</p>
      <span class="preset-chip">${preset.label}</span>
    </div>
  `).join('');
  panel.style.display = 'block';
}

function applyScreenerPreset(key, rerender = true) {
  const preset = SCREENER_PRESETS[key];
  if (!preset) return;

  _activePreset = key;
  _sortCol = preset.sortCol;
  _sortDir = preset.sortDir;

  const select = document.getElementById('screenerPreset');
  if (select) select.value = key;
  document.getElementById('screenerSignal').value = preset.signal;
  document.getElementById('screenerMinScore').value = preset.minScore;
  document.getElementById('activePresetLabel').textContent = `Using: ${preset.label}`;

  renderPresetStrip();
  renderInsightPanel();

  if (rerender && _screenerData.length) {
    renderSignalSummary(_screenerData);
    renderScreenerTable();
  }
}

function buildReasonChips(row) {
  const chips = [];

  if (row.passes_filter === false) chips.push({label: 'Hard filter fail', cls: 'bad'});
  if (row.rsi != null && Number(row.rsi) >= 55 && Number(row.rsi) <= 68) chips.push({label: `RSI ${Number(row.rsi).toFixed(1)}`});
  if (row.roe_pct != null && Number(row.roe_pct) >= 15) chips.push({label: `ROE ${Number(row.roe_pct).toFixed(1)}%`});

  if (!chips.length) chips.push({label: 'Needs manual review', cls: 'warn'});
  return chips.slice(0, 4).map(chip =>
    `<span class="reason-chip${chip.cls ? ` ${chip.cls}` : ''}">${chip.label}</span>`
  ).join('');
}

function updateScreenerSnapshot(rows) {
  const panel = document.getElementById('screenerSnapshot');
  if (!panel) return;
  if (!rows.length) {
    panel.style.display = 'none';
    return;
  }

  const topGrades = rows.filter(r => r.grade === 'A+' || r.grade === 'A').length;
  const breakouts = rows.filter(r => r.bb_breakout === true).length;
  const above50 = rows.filter(r => r.above_ema50).length;
  const breadth = rows.length ? Math.round((above50 / rows.length) * 100) : 0;

  document.getElementById('snapQualified').textContent = rows.length;
  document.getElementById('snapQualifiedFoot').textContent = `matching ${_currentPreset().label.toLowerCase()}`;
  document.getElementById('snapTopGrade').textContent = topGrades;
  document.getElementById('snapTopGradeFoot').textContent = `${rows.length ? Math.round((topGrades / rows.length) * 100) : 0}% of filtered basket`;
  document.getElementById('snapBreakouts').textContent = breakouts;
  document.getElementById('snapBreadth').textContent = `${breadth}%`;
  panel.style.display = 'grid';
}

async function refreshTodayReportStatus() {
  const btn = document.getElementById('downloadTodayBtn');
  if (!btn) return;
  btn.dataset.href = '/reports/today.csv';
}

function downloadModeCsv() {
  const modeCsvMap = {
    new: '/api/reports/new.csv',
    running: '/api/reports/running.csv',
    booked: '/api/reports/booked.csv'
  };
  window.location.href = modeCsvMap[_screenerMode];
}

function setScreenerMode(mode) {
  _screenerMode = mode;
  
  // Update switcher button active classes
  ['new', 'running', 'booked'].forEach(m => {
    const btn = document.getElementById(`mode-${m}`);
    if (btn) btn.classList.toggle('active', m === mode);
  });
  
  // Update CSV download button label
  const dlBtn = document.getElementById('downloadTodayBtn');
  if (dlBtn) {
    dlBtn.innerHTML = `&#8681; ${mode.toUpperCase()} CSV`;
  }
  
  loadScreenerModeData();
}

async function loadScreenerModeData() {
  const container = document.getElementById('screenerTable');
  if (container) {
    container.innerHTML = '<div style="color:var(--text3);font-family:var(--mono);font-size:10px;padding:20px">\u2637 Loading screener data…</div>';
  }
  
  const apiMap = {
    new: '/api/screener/new',
    running: '/api/screener/running',
    booked: '/api/screener/booked'
  };
  
  const url = apiMap[_screenerMode];
  try {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    
    _screenerData = data.results || [];
    
    // Hide presets bar/controls for non-new modes
    const presetStripHead = document.querySelector('.preset-strip');
    if (presetStripHead) {
      presetStripHead.style.display = _screenerMode === 'new' ? 'block' : 'none';
    }
    
    const sigControls = document.querySelector('.screener-controls');
    if (sigControls) {
      sigControls.style.display = _screenerMode === 'new' ? 'flex' : 'none';
    }
    
    const runBtn = document.getElementById('screenerRunBtn');
    if (runBtn) runBtn.style.display = _screenerMode === 'new' ? 'block' : 'none';
    
    const idxBtn = document.getElementById('screenerIdxBtn');
    if (idxBtn) idxBtn.style.display = _screenerMode === 'new' ? 'block' : 'none';
    
    const autoBadge = document.querySelector('.auto-badge');
    if (autoBadge) autoBadge.style.display = _screenerMode === 'new' ? 'inline-flex' : 'none';
    
    const sigPanel = document.getElementById('signalSummary');
    if (sigPanel) {
      sigPanel.style.display = _screenerMode === 'new' ? 'block' : 'none';
    }
    
    renderModeSummary(_screenerData);
    renderModeTable(_screenerData);
  } catch (e) {
    if (container) {
      container.innerHTML = `<div class="error-box">\u26a0 Error: ${e.message}</div>`;
    }
  }
}

function renderModeSummary(rows) {
  const panel = document.getElementById('screenerSnapshot');
  if (!panel) return;
  
  // Show all cards
  ['snapCard1', 'snapCard2', 'snapCard3', 'snapCard4'].forEach(id => {
    const card = document.getElementById(id);
    if (card) card.style.display = 'block';
  });
  
  if (_screenerMode === 'new') {
    const tradeEligible = rows.filter(r => r.trade_eligible === true).length;
    const activeTrades = rows.filter(r => r.trade_active === true && r.status === 'active').length;
    const todayQualified = rows.filter(r => r.days_in_screener === 0).length;
    
    document.getElementById('snapLabel1').textContent = 'Qualified';
    document.getElementById('snapQualified').textContent = rows.length;
    document.getElementById('snapQualifiedFoot').textContent = 'total qualified';
    
    document.getElementById('snapLabel2').textContent = 'Trade Eligible';
    document.getElementById('snapTopGrade').textContent = tradeEligible;
    document.getElementById('snapTopGradeFoot').textContent = 'score >= 65';
    
    document.getElementById('snapLabel3').textContent = 'Active Trades';
    document.getElementById('snapBreakouts').textContent = activeTrades;
    document.getElementById('snapBreakoutsFoot').textContent = 'currently tracked';
    
    document.getElementById('snapLabel4').textContent = 'Today Qualified';
    document.getElementById('snapBreadth').textContent = todayQualified;
    document.getElementById('snapBreadthFoot').textContent = 'first qualified today';
  }
  else if (_screenerMode === 'running') {
    const runningCount = rows.length;
    const winners = rows.filter(r => (r.pnl_pct ?? 0) > 0).length;
    const losers = rows.filter(r => (r.pnl_pct ?? 0) <= 0).length;

    // Calculate total P&L using last_price vs entry_price
    let totalPnlAmt = 0;
    let validPnlCount = 0;
    rows.forEach(r => {
      if (r.last_price != null && r.entry_price != null && r.entry_price > 0) {
        totalPnlAmt += (r.last_price - r.entry_price);
        validPnlCount++;
      }
    });
    const avgPnlPct = validPnlCount > 0
      ? rows.reduce((sum, r) => sum + (r.pnl_pct ?? 0), 0) / rows.length
      : 0;
    
    document.getElementById('snapLabel1').textContent = 'Active Positions';
    document.getElementById('snapQualified').textContent = runningCount;
    document.getElementById('snapQualifiedFoot').textContent = 'currently tracked';
    
    document.getElementById('snapLabel2').textContent = 'Unrealized P&L';
    const amtColor = totalPnlAmt >= 0 ? 'var(--accent)' : 'var(--red)';
    document.getElementById('snapTopGrade').innerHTML = `<span style="color:${amtColor}">₹${totalPnlAmt.toFixed(2)}</span>`;
    document.getElementById('snapTopGradeFoot').textContent = `Avg PnL: ${avgPnlPct.toFixed(2)}%`;
    
    document.getElementById('snapLabel3').textContent = 'Winners';
    document.getElementById('snapBreakouts').textContent = winners;
    document.getElementById('snapBreakoutsFoot').textContent = 'positive PnL';
    
    document.getElementById('snapLabel4').textContent = 'Losers';
    document.getElementById('snapBreadth').textContent = losers;
    document.getElementById('snapBreadthFoot').textContent = 'flat or negative PnL';
  }
  else if (_screenerMode === 'booked') {
    const bookedCount = rows.length;
    const targetHits = rows.filter(r => r.status === 'target_hit').length;
    const slHits = rows.filter(r => r.status === 'sl_hit' || r.status === 'trail_sl_hit').length;
    
    const realizedAmounts = rows.map(r => r.realized_amount).filter(a => a != null);
    const totalRealizedAmt = realizedAmounts.reduce((a, b) => a + b, 0);
    const entryPrices = rows.map(r => r.entry_price).filter(p => p != null);
    const totalEntryAmt = entryPrices.reduce((a, b) => a + b, 0);
    const avgPnlPct = totalEntryAmt ? (totalRealizedAmt / totalEntryAmt) * 100 : 0;
    
    document.getElementById('snapLabel1').textContent = 'Booked Count';
    document.getElementById('snapQualified').textContent = bookedCount;
    document.getElementById('snapQualifiedFoot').textContent = 'realized outcomes';
    
    document.getElementById('snapLabel2').textContent = 'Total Realized PnL';
    const amtColor = totalRealizedAmt >= 0 ? 'var(--accent)' : 'var(--red)';
    document.getElementById('snapTopGrade').innerHTML = `<span style="color:${amtColor}">₹${totalRealizedAmt.toFixed(2)}</span>`;
    document.getElementById('snapTopGradeFoot').textContent = `Avg PnL: ${avgPnlPct.toFixed(2)}%`;
    
    document.getElementById('snapLabel3').textContent = 'Target Hits';
    document.getElementById('snapBreakouts').textContent = targetHits;
    document.getElementById('snapBreakoutsFoot').textContent = 'targets reached';
    
    document.getElementById('snapLabel4').textContent = 'SL / Trail SL Hits';
    document.getElementById('snapBreadth').textContent = slHits;
    document.getElementById('snapBreadthFoot').textContent = 'stop loss triggered';
  }
  
  panel.style.display = 'grid';
}

function renderModeTable(rows) {
  if (_screenerMode === 'new') {
    renderScreenerTable();
    return;
  }
  
  const container = document.getElementById('screenerTable');
  if (!rows || !rows.length) {
    container.innerHTML = `<div class="screener-empty">NO STOCKS FOUND IN ${_screenerMode.toUpperCase()} MODE</div>`;
    return;
  }
  
  let sortedRows = [...rows];
  if (_screenerMode === 'running') {
    sortedRows.sort((a, b) => (b.pnl_pct ?? 0) - (a.pnl_pct ?? 0));
  } else if (_screenerMode === 'booked') {
    sortedRows.sort((a, b) => {
      const dateA = a.exit_at ? new Date(a.exit_at) : new Date(0);
      const dateB = b.exit_at ? new Date(b.exit_at) : new Date(0);
      return dateB - dateA;
    });
  }
  
  const fmtDate = (dStr) => {
    if (!dStr) return '—';
    try {
      const d = new Date(dStr);
      if (isNaN(d.getTime())) return dStr;
      return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
    } catch (e) {
      return dStr;
    }
  };
  
  const fmtPrice = (p) => (p != null && !isNaN(p)) ? `₹${Number(p).toFixed(2)}` : '—';
  const fmtPct = (p) => (p != null && !isNaN(p)) ? `${Number(p).toFixed(2)}%` : '—';
  
  if (_screenerMode === 'running') {
    const tableHeader = `
      <thead>
        <tr>
          <th>TICKER</th>
          <th>ENTRY DATE</th>
          <th>ENTRY PRICE</th>
          <th>CURRENT PRICE</th>
          <th>TARGET</th>
          <th>SL</th>
          <th>TRAIL SL</th>
          <th>HIGHEST</th>
          <th>PNL %</th>
          <th>PNL ₹</th>
          <th>DAYS</th>
        </tr>
      </thead>
    `;
    
    const tableBody = sortedRows.map(r => {
      const pnlCol = (r.pnl_pct ?? 0) >= 0 ? 'var(--accent)' : 'var(--red)';
      return `
        <tr onclick="openCpByTicker('${r.ticker}')" style="cursor:pointer" title="Click to chart">
          <td class="td-ticker">${r.ticker}</td>
          <td class="td-mono">${fmtDate(r.entry_at)}</td>
          <td class="td-mono">${fmtPrice(r.entry_price)}</td>
          <td class="td-mono">${fmtPrice(r.last_price)}</td>
          <td class="td-mono">${fmtPrice(r.target_price)}</td>
          <td class="td-mono" style="color:var(--red)">${fmtPrice(r.sl_price)}</td>
          <td class="td-mono" style="color:var(--warn)">${fmtPrice(r.current_trail_sl)}</td>
          <td class="td-mono">${fmtPrice(r.highest_price)}</td>
          <td class="td-mono" style="color:${pnlCol};font-weight:700">${fmtPct(r.pnl_pct)}</td>
          <td class="td-mono" style="color:${pnlCol};font-weight:700">${fmtPrice(r.running_amount)}</td>
          <td class="td-mono">${r.days_running ?? 0}</td>
        </tr>
      `;
    }).join('');
    
    container.innerHTML = `
      <div class="screener-count">${sortedRows.length} active tracked positions with current score >= 70 &middot; click any row to view chart</div>
      <div class="screener-tbl-wrap">
        <table class="screener-tbl">
          ${tableHeader}
          <tbody>${tableBody}</tbody>
        </table>
      </div>
    `;
  }
  else if (_screenerMode === 'booked') {
    const tableHeader = `
      <thead>
        <tr>
          <th>TICKER</th>
          <th>ENTRY DATE</th>
          <th>EXIT DATE</th>
          <th>ENTRY PRICE</th>
          <th>EXIT PRICE</th>
          <th>BOOKED %</th>
          <th>BOOKED ₹</th>
          <th>EXIT TYPE</th>
          <th>HIGHEST</th>
          <th>DAYS HELD</th>
        </tr>
      </thead>
    `;
    
    const tableBody = sortedRows.map(r => {
      const pnlCol = (r.realized_pnl_pct ?? 0) >= 0 ? 'var(--accent)' : 'var(--red)';
      let exitTypeBadge = '';
      if (r.status === 'target_hit') {
        exitTypeBadge = `<span class="signal-pill pill-buy" style="padding:2px 8px;font-size:10px">TARGET</span>`;
      } else if (r.status === 'sl_hit') {
        exitTypeBadge = `<span class="signal-pill pill-skip" style="padding:2px 8px;font-size:10px">FIXED SL</span>`;
      } else if (r.status === 'trail_sl_hit') {
        exitTypeBadge = `<span class="signal-pill pill-watch" style="padding:2px 8px;font-size:10px">TRAIL SL</span>`;
      } else {
        exitTypeBadge = `<span class="signal-pill pill-neutral" style="padding:2px 8px;font-size:10px">${r.status.toUpperCase()}</span>`;
      }
      
      return `
        <tr onclick="openCpByTicker('${r.ticker}')" style="cursor:pointer" title="Click to chart">
          <td class="td-ticker">${r.ticker}</td>
          <td class="td-mono">${fmtDate(r.entry_at)}</td>
          <td class="td-mono">${fmtDate(r.exit_at)}</td>
          <td class="td-mono">${fmtPrice(r.entry_price)}</td>
          <td class="td-mono">${fmtPrice(r.exit_price)}</td>
          <td class="td-mono" style="color:${pnlCol};font-weight:700">${fmtPct(r.realized_pnl_pct)}</td>
          <td class="td-mono" style="color:${pnlCol};font-weight:700">${fmtPrice(r.realized_amount)}</td>
          <td>${exitTypeBadge}</td>
          <td class="td-mono">${fmtPrice(r.highest_price)}</td>
          <td class="td-mono">${r.holding_days ?? 0}</td>
        </tr>
      `;
    }).join('');
    
    container.innerHTML = `
      <div class="screener-count">${sortedRows.length} realized positions \u00b7 click any row to view chart</div>
      <div class="screener-tbl-wrap">
        <table class="screener-tbl">
          ${tableHeader}
          <tbody>${tableBody}</tbody>
        </table>
      </div>
    `;
  }
}

function downloadTodayReport() {
  window.location.href = '/reports/today.csv';
}

// runScreener is called by the ⚡ RUN button — delegates to background screener
async function runScreener() {
  await _startBgScreener(getSelectedIndexParam());
}

function _filterScreener(rows) {
  const sig = document.getElementById('screenerSignal').value;
  const minScore = Number(document.getElementById('screenerMinScore').value || 0);

  return rows.filter(r => {
    if ((r.total_score ?? 0) < minScore) return false;
    if (sig === 'breakout') return r.bb_breakout === true;
    if (sig === 'squeeze')  return !r.bb_breakout && (r.bb_squeeze_pct ?? 100) <= 30;
    if (sig === 'buy')      return (r.grade === 'A+' || r.grade === 'A');
    return true;
  });
}

function renderScreenerTable() {
  const container = document.getElementById('screenerTable');
  let rows = _filterScreener([..._screenerData]);
  rows.sort((a, b) => _sortDir * ((b[_sortCol] ?? 0) - (a[_sortCol] ?? 0)));
  updateScreenerSnapshot(rows);

  if (!rows.length) {
    container.innerHTML = '<div class="screener-empty">NO STOCKS MATCH YOUR FILTERS</div>';
    return;
  }

  const cols = [
    {key:'ticker',           label:'TICKER'},
    {key:'days_in_screener', label:'SINCE'},
    {key:'total_score',      label:'SCORE'},
    {key:'grade',            label:'GRD'},
    {key:'passes_filter',    label:'FILTER'},
    {key:'signal',           label:'SIGNAL'},
    {key:'ruling_planets',   label:'ASTRO'},
    {key:'rsi',              label:'RSI'},
    {key:'roe_pct',          label:'ROE %'},
    {key:'roce_pct',         label:'ROCE %'},
    {key:'eps',              label:'EPS \u20b9'},
    {key:'debt_equity',      label:'D/E'},
    {key:'close',            label:'CLOSE \u20b9'},
    {key:'delivery_pct',     label:'DELV %'},
    {key:'reasons',          label:'WHY IT QUALIFIED'},
  ];

  // styled N/A badge for missing values
  const na = () => '<span style="color:var(--text3);font-size:9px;letter-spacing:.05em;opacity:.6">N/A</span>';
  const fmtN = (v, d) => (v != null && !isNaN(Number(v))) ? Number(v).toFixed(d) : null;

  // Indian compact volume formatter  — AngelOne style
  // 6,347,884  → "63.5L"   |  34,500 → "34.5K"   |  1,20,00,000 → "1.2Cr"
  const fmtVol = v => {
    if (v == null || isNaN(v)) return null;
    const n = Number(v);
    if (n >= 1e7)  return (n / 1e7).toFixed(2).replace(/\.?0+$/, '') + 'Cr';
    if (n >= 1e5)  return (n / 1e5).toFixed(2).replace(/\.?0+$/, '') + 'L';
    if (n >= 1e3)  return (n / 1e3).toFixed(2).replace(/\.?0+$/, '') + 'K';
    return String(Math.round(n));
  };

  // threshold colour helpers
  const cROE  = v => v == null ? '' : `color:${v>=15?'var(--accent)':v>=10?'var(--warn)':'var(--red)'}`;
  const cROCE = v => v == null ? '' : `color:${v>=15?'var(--accent)':v>=8 ?'var(--warn)':'var(--red)'}`;
  const cDE   = v => v == null ? '' : `color:${v<=0.5?'var(--accent)':v<=0.8?'var(--warn)':'var(--red)'}`;
  const cEPS  = v => v == null ? '' : `color:${v>0?'var(--accent)':'var(--red)'}`;
  const cATR  = v => v == null ? '' : `color:${v>25?'var(--accent)':'var(--warn)'}`;
  const cADX  = v => v == null ? '' : `color:${v>=25?'var(--accent)':v>=20?'var(--warn)':'var(--red)'}`;

  const ths = cols.map(c => {
    const cls = c.key === _sortCol ? (_sortDir === -1 ? 'sort-desc' : 'sort-asc') : '';
    return `<th class="${cls}" onclick="sortScreener('${c.key}')" style="cursor:pointer">${c.label}</th>`;
  }).join('');

  const tds = rows.map(r => {
    const sc     = r.total_score ?? 0;
    const scCol  = sc>=70?'var(--accent)':sc>=55?'var(--warn)':'var(--red)';
    const sigCls = (r.signal||'').includes('BUY')?'pill-buy':(r.signal||'').includes('WATCH')?'pill-watch':'pill-neutral';

    const bbPill = r.bb_breakout
      ? `<span class="brk-pill">BREAKOUT</span>`
      : (r.bb_squeeze_pct!=null && r.bb_squeeze_pct<=30)
        ? `<span class="brk-pill sqz-pill">SQUEEZE</span>`
        : `<span class="brk-pill neut-pill">\u2014</span>`;

    const gcPill = r.golden_cross ? `<span class="brk-pill">GC</span>` : na();
    const ema50  = r.above_ema50  ? '\u2705 ABOVE' : '\u274c BELOW';

    const fBadge = (r.passes_filter===false)
      ? `<span style="color:var(--red);font-weight:700" title="Fails D/E>0.5 or EPS\u22640">\u2717 FAIL</span>`
      : `<span style="color:var(--accent);font-weight:700" title="Passes all hard filters">\u2713 PASS</span>`;

    const astStatus = r.transit_status || 'Neutral';
    const astCol    = astStatus === 'Upside' ? 'var(--accent)' : astStatus === 'Downside' ? 'var(--red)' : 'var(--warn)';
    const astIcon   = astStatus === 'Upside' ? '🟢' : astStatus === 'Downside' ? '🔴' : '🟡';
    const astBadge  = `<span style="color:${astCol};font-weight:700;font-size:10px" title="Ruling Planet: ${r.ruling_planets || 'Jup'} | Transit Status: ${astStatus}">${astIcon} ${r.ruling_planets || 'Jup'}</span>`;

    const roeV  = fmtN(r.roe_pct,   1);
    const roceV = fmtN(r.roce_pct,  1);
    const epsV  = fmtN(r.eps,       2);
    const deV   = fmtN(r.debt_equity,2);
    const atrV  = fmtN(r.atr,       1);
    const adxV  = fmtN(r.adx,       1);
    const rsiV  = fmtN(r.rsi,       1);
    const volV  = fmtN(r.volume_ratio, 2);
    const volRaw = fmtVol(r.last_volume);  // e.g. "63.5L"
    const rsV   = fmtN(r.rs_vs_nifty,3);
    const tradeBadge = r.trade_active ? ` <span class="brk-pill" style="background:rgba(34,197,94,0.15);color:var(--green);border-color:rgba(34,197,94,0.3);margin-left:4px;font-size:8px;padding:1px 4px" title="Simulation Active">SIM</span>` : '';

    // SINCE badge: show the active scan date
    const daysIn    = r.days_in_screener != null ? Number(r.days_in_screener) : null;
    const firstDate = r.first_seen || null;
    const scanDate  = r.scan_date || firstDate || null;
    let sinceBadge;
    if (daysIn === null || !scanDate) {
      sinceBadge = na();
    } else if (daysIn === 0) {
      sinceBadge = `<span style="background:var(--accent);color:#0a0f1a;font-size:9px;font-weight:800;letter-spacing:.06em;padding:2px 6px;border-radius:4px" title="First seen: ${firstDate || scanDate}">NEW</span>`;
    } else {
      let dateStr = scanDate;
      try {
        const parts = scanDate.split('/');
        if (parts.length === 3) {
          const d = new Date(parts[2], parts[1] - 1, parts[0]);
          if (!isNaN(d.getTime())) {
            dateStr = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
          }
        } else {
          const d2 = new Date(scanDate);
          if (!isNaN(d2.getTime())) {
            dateStr = d2.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
          } else {
            const year = new Date().getFullYear();
            const d3 = new Date(`${scanDate} ${year}`);
            if (!isNaN(d3.getTime())) {
              dateStr = d3.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
            }
          }
        }
      } catch (e) {
        console.warn('Date parsing failed:', scanDate, e);
      }
      sinceBadge = `<span class="td-mono" style="color:var(--text2);font-size:10px" title="First qualified: ${firstDate || scanDate}">${dateStr}</span>`;
    }

    return `<tr onclick="openCpFromRow(event,'${r.ticker}','${r.sector||''}','${r.transit_status||'Neutral'}','${r.ruling_planets||'Jup'}',${r.astro_score||3})" title="Click to chart · Shift+click to analyse">
      <td class="td-ticker">${r.ticker}${tradeBadge}</td>
      <td style="text-align:center">${sinceBadge}</td>
      <td class="td-score"><span class="quality-score-badge ${sc>=70?'good':sc>=55?'warn':'bad'}">${sc}</span></td>
      <td class="td-mono">${r.grade ?? na()}</td>
      <td>${fBadge}</td>
      <td><span class="signal-pill ${sigCls}" style="padding:2px 8px;font-size:10px">\u25cf ${r.signal??'\u2014'}</span></td>
      <td>${astBadge}</td>
      <td class="td-mono">${rsiV!=null?rsiV:na()}</td>
      <td class="td-mono" style="${cROE(roeV!=null?+roeV:null)}">${roeV!=null?roeV+'%':na()}</td>
      <td class="td-mono" style="${cROCE(roceV!=null?+roceV:null)}">${roceV!=null?roceV+'%':na()}</td>
      <td class="td-mono" style="${cEPS(epsV!=null?+epsV:null)}">${epsV!=null?'\u20b9'+epsV:na()}</td>
      <td class="td-mono" style="${cDE(deV!=null?+deV:null)}">${deV!=null?deV:na()}</td>
      <td class="td-mono">${r.close!=null?'\u20b9'+Number(r.close).toFixed(2):na()}</td>
      <td class="td-mono">${r.delivery_pct!=null?Number(r.delivery_pct).toFixed(1)+'%':na()}</td>
      <td class="td-reason"><div class="reason-stack">${buildReasonChips(r)}</div></td>
    </tr>`;
  }).join('');

  container.innerHTML =
    `<div class="screener-count">${rows.length} stocks matched \u00b7 click any row to analyse</div>
     <div class="screener-tbl-wrap">
       <table class="screener-tbl">
         <thead><tr>${ths}</tr></thead>
         <tbody>${tds}</tbody>
       </table>
     </div>`;
}


function sortScreener(col) {
  if (col === 'reasons') return;
  if (_sortCol === col) { _sortDir *= -1; }
  else { _sortCol = col; _sortDir = -1; }
  renderScreenerTable();
}

// Re-filter on signal dropdown change without re-fetching
document.getElementById('screenerSignal')?.addEventListener('change', () => {
  if (_screenerData.length) renderScreenerTable();
});
document.getElementById('screenerMinScore')?.addEventListener('change', () => {
  if (_screenerData.length) renderScreenerTable();
});
document.getElementById('screenerPreset')?.addEventListener('change', e => {
  applyScreenerPreset(e.target.value);
});

/* ── Index Modal ────────────────────────────────────────────────────────── */
let _backendAllCount = 500;
let _backendN500Count = 500;
let _backendN50Count = 50;
let _backendNext50Count = 50;

const _IDX_SIZES = { 
  'idx-nifty50': 50, 
  'idx-next50': 50, 
  'idx-nifty500': 500, 
  'idx-all': 500 
};
const _IDX_KEYS  = { 
  'idx-nifty50': 'nifty50',
  'idx-next50': 'next50',
  'idx-nifty500': 'nifty500_custom',
  'idx-all': 'all' 
};
const _IDX_IDS   = Object.keys(_IDX_SIZES);

function openIndexModal()  { document.getElementById('indexModal').style.display = 'flex'; updateModalCount(); }
function closeIndexModal() { document.getElementById('indexModal').style.display = 'none'; }
function selectAllIndices() { _IDX_IDS.forEach(id => { const el = document.getElementById(id); if (el) el.checked = true; }); updateModalCount(); }
function clearAllIndices()  { _IDX_IDS.forEach(id => { const el = document.getElementById(id); if (el) el.checked = false; }); updateModalCount(); }

async function fetchBackendUniverseCounts() {
  try {
    const data = await fetch(`${API_BASE}/universe?index=all`).then(r => r.json());
    if (data.counts) {
      _backendAllCount = data.counts.all || 500;
      _backendN500Count = data.counts.nifty500_custom || 500;
      _backendN50Count = data.counts.nifty50 || 50;
      _backendNext50Count = data.counts.next50 || 50;
    }
    
    // Update labels dynamically
    const lblN50 = document.querySelector('#lbl-nifty50 .idx-count');
    if (lblN50) lblN50.textContent = `${_backendN50Count} stocks`;
    
    const lblNext50 = document.querySelector('#lbl-next50 .idx-count');
    if (lblNext50) lblNext50.textContent = `${_backendNext50Count} stocks`;

    const lblN500 = document.querySelector('#lbl-nifty500 .idx-count');
    if (lblN500) lblN500.textContent = `${_backendN500Count} stocks`;
    
    const lblAll = document.querySelector('#lbl-all .idx-count');
    if (lblAll) lblAll.textContent = `${_backendAllCount} stocks`;
    
    updateModalCount();
  } catch (e) {
    console.warn('Failed to fetch backend universe counts:', e);
  }
}

let _lastAllChecked = false;

async function updateModalCount() {
  const allEl = document.getElementById('idx-all');
  const individualIds = _IDX_IDS.filter(id => id !== 'idx-all');
  
  if (allEl) {
    const allChecked = allEl.checked;
    if (allChecked !== _lastAllChecked) {
      individualIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = allChecked;
      });
      _lastAllChecked = allChecked;
    } else {
      const allIndivChecked = individualIds.every(id => document.getElementById(id)?.checked);
      allEl.checked = allIndivChecked;
      _lastAllChecked = allIndivChecked;
    }
  }

  const checked = _IDX_IDS.filter(id => document.getElementById(id)?.checked);
  const selectedKeys = checked.map(id => _IDX_KEYS[id]);
  
  let total = 0;
  let indexParam = selectedKeys.join(',');
  if (!checked.length || checked.includes('idx-all')) {
    indexParam = 'all';
  }
  
  try {
    const data = await fetch(`${API_BASE}/universe?index=${encodeURIComponent(indexParam)}`).then(r => r.json());
    total = data.total || 0;
  } catch (e) {
    // fallback approximate math if fetch fails
    total = checked.includes('idx-all') ? _backendAllCount : _backendN500Count;
  }
  
  const est = Math.max(1, Math.ceil(total * 2.5 / 60));
  if (!checked.length) {
    document.getElementById('modalTotalCount').textContent =
      `No indices checked (will scan all indices by default) · ${total} unique stocks · Est. ~${est} min`;
  } else {
    document.getElementById('modalTotalCount').textContent =
      `${total} unique stocks selected (overlaps deduped) · Est. ~${est} min`;
  }


  _refreshDropdown(getSelectedIndexParam());
}

function getSelectedIndexParam() {
  const checked = _IDX_IDS.filter(id => document.getElementById(id)?.checked);
  if (!checked.length) return 'all';
  return checked.map(id => _IDX_KEYS[id]).join(',');
}


async function applyAndRun() {
  const indexParam = getSelectedIndexParam();
  closeIndexModal();
  // Refresh dropdown with the final selection
  await _refreshDropdown(indexParam);
  await _startBgScreener(indexParam);
}

/* ── Background screener (non-blocking) ─────────────────────────────────── */
let _pollTimer    = null;
let _liveMode     = true;   // always on — AUTO is now a permanent feature
let _liveTimer    = null;

async function runScreener() {
  await _startBgScreener(getSelectedIndexParam());
}

async function _startBgScreener(indexParam) {
  const minScore = document.getElementById('screenerMinScore').value || 0;
  const btn = document.getElementById('screenerRunBtn');

  btn.disabled = true;
  _showProgress(true, 0, 0);

  try {
    const resp = await fetch(`${API_BASE}/screener/run?index=${encodeURIComponent(indexParam)}&min_score=${minScore}`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      // Already running — just start polling
      if (resp.status === 409) { _pollStatus(); return; }
      _showProgress(false);
      btn.disabled = false;
      document.getElementById('screenerStatus').style.display = 'block';
      document.getElementById('screenerStatus').textContent   = `⚠ ${data.error || 'Start failed'}`;
      return;
    }
    _pollStatus();
  } catch(e) {
    _showProgress(false);
    btn.disabled = false;
  }
}

function _pollStatus() {
  clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    try {
      const s = await fetch(`${API_BASE}/screener/status`).then(r => r.json());
      _showProgress(s.running, s.progress, s.total, s.pct);

      if (!s.running) {
        clearInterval(_pollTimer);
        _showProgress(false);
        const runBtn = document.getElementById('screenerRunBtn');
        if (runBtn) runBtn.disabled = false;

        if (s.error) {
          const errEl = document.getElementById('screenerStatus');
          if (errEl) {
            errEl.style.display  = 'block';
            errEl.textContent = `⚠ ${s.error}`;
          }
          return;
        }
        
        // If we are currently in "new" mode, load the results and render
        if (_screenerMode === 'new') {
          const latest = await fetch(`${API_BASE}/screener/latest`).then(r => r.json());
          _screenerData = latest.results || [];
          renderScreenerTable();
          renderSignalSummary(_screenerData);          // grade breakdown + top picks panel
          _updateLiveTimestamp(latest.finished_at);
          _checkAndNotify(_screenerData);
          refreshTodayReportStatus();
        } else {
          // If in running/booked mode, just refresh that mode's data
          loadScreenerModeData();
        }
      }
    } catch(e) { /* network hiccup — keep polling */ }
  }, 2000);
}

function _showProgress(visible, done=0, total=0, pct=0) {
  const p = document.getElementById('screenerProgress');
  if (!p) return;
  p.style.display = visible ? 'block' : 'none';
  if (visible) {
    let text = `⚡ SCANNING ${done}/${total} STOCKS`;
    if (total > 300) {
      text = `⚡ FULL-MARKET SCANNING ${done}/${total} STOCKS · Est. ~15-20 min`;
    } else if (total > 0) {
      const est = Math.max(1, Math.ceil(total * 2.5 / 60));
      text = `⚡ SCANNING ${done}/${total} STOCKS · Est. ~${est} min`;
    }
    document.getElementById('progressLabel').textContent = text;
    document.getElementById('progressPct').textContent   = `${pct}%`;
    document.getElementById('progressBar').style.width   = `${pct}%`;
  }
}


function _updateLiveTimestamp(iso) {
  const el = document.getElementById('liveTimestamp');
  if (!el || !iso) return;
  const t = new Date(iso);
  el.style.display   = 'block';
  el.textContent     = `📡 Last updated: ${t.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'})} IST`;
}

/* ── Live / Auto-refresh mode — always on ──────────────────────────────── */
// AUTO is now a default always-on feature. toggleLiveMode kept as no-op
// in case any old reference calls it.
// in case any old reference calls it.
function toggleLiveMode() { /* no-op — AUTO is always active */ }

function _startAutoRefresh() {
  _liveMode  = true;
  clearInterval(_liveTimer);
  _loadLatestResults();                                          // immediate
  _liveTimer = setInterval(_loadLatestResults, 5 * 60 * 1000); // every 5 min
}

async function _loadLatestResults() {
  try {
    refreshTodayReportStatus();
    const data = await fetch(`${API_BASE}/screener/latest`).then(r => r.json());
    if (_screenerMode === 'new') {
      if (data.results && data.results.length) {
        _screenerData = data.results;
        renderScreenerTable();
        renderSignalSummary(_screenerData);
        _updateLiveTimestamp(data.finished_at);
        _checkAndNotify(_screenerData);
        // Keep sector intelligence data cache fresh and updated silently in background
        loadSectorData(true);
      }
    } else {
      loadScreenerModeData();
    }
    if (data.running) _pollStatus();
  } catch(e) {}
}

/* ── Signal Summary Panel ─────────────────────────────────────────────────── */
function renderSignalSummary(results) {
  const panel     = document.getElementById('signalSummary');
  const pillsEl   = document.getElementById('gradePills');
  const picksEl   = document.getElementById('topPicksTable');
  const filtered = _filterScreener([...(results || [])]);
  if (!panel || !filtered.length) {
    if (panel) panel.style.display = 'none';
    return;
  }

  // Grade bucket counts
  const buckets = { 'A+': [], 'A': [], 'B': [], 'C': [], 'D': [] };
  filtered.forEach(r => {
    const g = r.grade || 'D';
    if (buckets[g]) buckets[g].push(r);
  });

  const pillCfg = {
    'A+': { bg:'rgba(0,255,136,.18)', color:'var(--accent)',  label:'A+ Strong Buy' },
    'A':  { bg:'rgba(0,200,100,.14)', color:'#00cc78',        label:'A  Buy'         },
    'B':  { bg:'rgba(255,200,50,.14)', color:'var(--warn)',   label:'B  Watch'       },
    'C':  { bg:'rgba(255,100,50,.12)', color:'#ff7043',       label:'C  Neutral'     },
    'D':  { bg:'rgba(255,50,50,.10)', color:'var(--red)',     label:'D  Skip'        },
  };

  pillsEl.innerHTML = Object.entries(buckets).map(([grade, stocks]) => `
    <div style="background:${pillCfg[grade].bg};border:1px solid ${pillCfg[grade].color}33;
      border-radius:8px;padding:8px 14px;min-width:90px;text-align:center">
      <div style="color:${pillCfg[grade].color};font-size:18px;font-weight:700;font-family:var(--mono)">${stocks.length}</div>
      <div style="color:var(--text3);font-size:9px;letter-spacing:.06em;margin-top:2px">${pillCfg[grade].label}</div>
    </div>`).join('');

  // Top picks: A+ first, then A, then B — max 8
  const qualify = [...(buckets['A+']), ...(buckets['A']), ...(buckets['B'])]
    .sort((a, b) => (b.total_score||0) - (a.total_score||0))
    .slice(0, 8);

  if (!qualify.length) {
    picksEl.innerHTML = '<div style="color:var(--text3);font-size:11px;padding:8px 0">No A/B grade stocks found in this scan.</div>';
    panel.style.display = 'block';
    return;
  }

  const fmt2 = v => v != null && !isNaN(+v) ? Number(v).toFixed(2) : '\u2014';
  const fmt1 = v => v != null && !isNaN(+v) ? Number(v).toFixed(1) : '\u2014';
  const gradeColor = g => g==='A+'?'var(--accent)':g==='A'?'#00cc78':g==='B'?'var(--warn)':'var(--text3)';

  const rows = qualify.map(r => {
    // SINCE badge: show actual date the ticker first appeared
    const daysIn    = r.days_in_screener != null ? Number(r.days_in_screener) : null;
    const firstDate = r.first_seen || null;
    const scanDate  = r.scan_date || firstDate || null;
    let sinceBadge;
    if (daysIn === null || !scanDate) {
      sinceBadge = '<span style="color:var(--text3);font-size:9px;opacity:.5">—</span>';
    } else if (daysIn === 0) {
      sinceBadge = `<span style="background:var(--accent);color:#0a0f1a;font-size:9px;font-weight:800;letter-spacing:.06em;padding:2px 6px;border-radius:4px" title="First seen: ${firstDate || scanDate}">NEW</span>`;
    } else {
      const parts = scanDate.split('/');
      const d = parts.length === 3 ? new Date(parts[2], parts[1] - 1, parts[0]) : new Date(scanDate);
      const dateStr = d.toLocaleDateString('en-IN', { day:'2-digit', month:'short' });
      sinceBadge = `<span style="color:var(--text2);font-size:10px;font-family:var(--mono)" title="First qualified: ${firstDate || scanDate}">${dateStr}</span>`;
    }
    return `
    <tr onclick="openCpFromRow(event,'${r.ticker}','${r.sector||''}','${r.transit_status||'Neutral'}','${r.ruling_planets||'Jup'}',${r.astro_score||3})" style="cursor:pointer" title="Click to chart · Shift+click to analyse">
      <td class="td-ticker" style="padding:6px 10px">${r.ticker}</td>
      <td style="padding:6px 8px;text-align:center">${sinceBadge}</td>
      <td class="td-score" style="color:${gradeColor(r.grade)};padding:6px 8px">${r.total_score}</td>
      <td style="padding:6px 8px">
        <span style="background:${gradeColor(r.grade)}22;color:${gradeColor(r.grade)};
          border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700">${r.grade}</span>
      </td>
      <td class="td-mono" style="color:var(--text2);font-size:10px;padding:6px 8px">${r.signal||'\u2014'}</td>
      <td class="td-mono" style="padding:6px 8px">${r.close!=null?'\u20b9'+fmt2(r.close):'\u2014'}</td>
      <td class="td-mono" style="padding:6px 8px" id="tp-ltp-${r.ticker}">
        <span style="color:var(--text3);font-size:9px;letter-spacing:.04em">…</span>
      </td>
      <td class="td-mono" style="color:var(--red);padding:6px 8px">${r.stop_loss!=null?'\u20b9'+fmt2(r.stop_loss):'\u2014'}</td>
      <td class="td-mono" style="padding:6px 8px">${fmt1(r.rsi)}</td>
      <td class="td-mono" style="padding:6px 8px">${r.atr!=null?'\u20b9'+fmt1(r.atr):'\u2014'}</td>
      <td class="td-mono" style="color:${r.passes_filter===false?'var(--red)':'var(--accent)'};padding:6px 8px">
        ${r.passes_filter===false?'\u2717 FAIL':'\u2713 PASS'}
      </td>
    </tr>`;
  }).join('');

  picksEl.innerHTML = `
    <table class="screener-tbl" style="width:100%">
      <thead>
        <tr>
          <th>TICKER</th><th style="color:var(--accent)">SINCE</th><th>SCORE</th><th>GRD</th><th>SIGNAL</th>
          <th>CLOSE</th><th style="color:var(--accent)">LTP &#9679;</th><th>STOP</th><th>RSI</th><th>ATR</th><th>FILTER</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;

  panel.style.display = 'block';

  // ── Live LTP injection (single batch call → avoids Angel One rate-limit) ────
  // All tickers are fetched server-side with 0.35 s gaps; one request from JS.
  // When market is closed Angel One returns null → fall back to last CLOSE price.
  const _ltpTickers = qualify.map(r => r.ticker).join(',');
  fetch(`${API_BASE}/ltp/batch?tickers=${encodeURIComponent(_ltpTickers)}`)
    .then(res => res.json())
    .then(data => {
      const ltpMap = data.ltps || {};
      qualify.forEach(r => {
        const cell  = document.getElementById(`tp-ltp-${r.ticker}`);
        if (!cell) return;
        const ltp   = ltpMap[r.ticker];
        const close = r.close != null ? Number(r.close) : null;

        if (ltp == null) {
          // Market closed — show last closing price with CLOSED badge
          if (close != null) {
            cell.innerHTML = `<span style="color:var(--text2);font-weight:600">\u20b9${close.toFixed(2)}</span>`
                           + `<span style="font-size:8px;color:var(--text3);margin-left:4px;letter-spacing:.04em">CLOSED</span>`;
          } else {
            cell.innerHTML = '<span style="color:var(--text3);font-size:9px">N/A</span>';
          }
          return;
        }

        // Market open — show live LTP with change since previous scan today
        const diff    = r.ltp_change_since_scan;
        const diffStr = diff != null
          ? ` <span style="font-size:9px;color:${diff>=0?'var(--accent)':'var(--red)'};margin-left:3px">${diff>=0?'+':''}${Number(diff).toFixed(2)}</span>`
          : ` <span style="font-size:9px;color:var(--text3);margin-left:3px">—</span>`;
        cell.innerHTML = `<span style="color:var(--accent);font-weight:600">\u20b9${Number(ltp).toFixed(2)}</span>${diffStr}`;
      });
    })
    .catch(() => {
      qualify.forEach(r => {
        const cell = document.getElementById(`tp-ltp-${r.ticker}`);
        if (cell) cell.innerHTML = '<span style="color:var(--text3);font-size:9px">—</span>';
      });
    });
}


// On page load: start auto-refresh immediately (screener is default view)
document.addEventListener('DOMContentLoaded', () => {
  initThemeToggle();
  initScreenerPresets();
  refreshTodayReportStatus();
  _startAutoRefresh();
  _initNotifications();   // boot notification permission engine
  _startNotificationPolling(); // start checking in-app notifications
  _refreshDropdown(getSelectedIndexParam());
  fetchBackendUniverseCounts();
});



/* ═══════════════════════════════════════════════════════════════════════════
   BROWSER NOTIFICATION ENGINE
   ─────────────────────────────────────────────────────────────────────────
   Flow:
     1. On first open → show custom "Allow Alerts" dialog
     2. User clicks ALLOW → browser native permission prompt fires
     3. Permission stored in localStorage (cookie-equivalent)
     4. Every time screener completes → scan results for A/A+ signals
     5. Fire native OS push notification + in-page toast for each
   ═══════════════════════════════════════════════════════════════════════════ */

const _NOTIF_KEY      = 'nse_notif_pref';
const _NOTIF_SEEN_KEY = 'nse_notif_asked';
// Grades that trigger alerts: Strong Buy (A+), Buy (A), Watch (B = satisfactory)
const _SIGNAL_QUALIFY = ['Strong Buy', 'Buy', 'Watch'];

function _initNotifications() {
  const pref = localStorage.getItem(_NOTIF_KEY);
  // Already decided — don't show dialog again
  if (pref === 'granted' || pref === 'denied') return;
  // Not asked yet — show dialog after 3 seconds (let page load first)
  setTimeout(() => {
    document.getElementById('notifPermModal').style.display = 'flex';
  }, 3000);
}

function grantNotifPermission() {
  if (!('Notification' in window)) {
    alert('Your browser does not support desktop notifications.');
    dismissNotifModal();
    return;
  }
  Notification.requestPermission().then(result => {
    localStorage.setItem(_NOTIF_KEY, result);  // 'granted' or 'denied'
    dismissNotifModal();
    if (result === 'granted') {
      // Confirm to user it worked
      new Notification('NSE Screener Alerts Active', {
        body: 'You will be notified when strong Grade A signals are detected.',
        icon: '/static/img/favicon.png',
        tag:  'nse-init'
      });
    }
  });
}

function dismissNotifModal() {
  document.getElementById('notifPermModal').style.display = 'none';
  // If they clicked "Not Now", store so we don't pester again this session
  if (!localStorage.getItem(_NOTIF_KEY)) {
    localStorage.setItem(_NOTIF_KEY, 'dismissed');
  }
}

/* ── Scan results and fire alerts for qualifying signals ─────────────────── */
function _checkAndNotify(results) {
  if (!results || !results.length) return;

  const pref = localStorage.getItem(_NOTIF_KEY);
  const canPush = pref === 'granted' && Notification.permission === 'granted';

  // Filter: only Grade A/A+ or Strong Buy / Buy signals that pass fund filter
  const top = results
    .filter(r => _SIGNAL_QUALIFY.some(s => (r.signal || '').includes(s)) && r.passes_filter !== false)
    .sort((a, b) => (b.total_score || 0) - (a.total_score || 0))
    .slice(0, 5);   // max 5 in one batch

  if (!top.length) return;

  const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  const idxLabel = getSelectedIndexParam().toUpperCase();

  // ── In-page Toast ─────────────────────────────────────────────────────────
  const lines = top.map(r => {
    const gr   = r.grade || '';
    const sig  = r.signal || '';
    const cls  = r.close  != null ? '\u20b9' + Number(r.close).toFixed(2) : '—';
    const sl   = r.stop_loss != null ? '\u20b9' + Number(r.stop_loss).toFixed(2) : '—';
    const rsi  = r.rsi  != null ? Number(r.rsi).toFixed(1) : '—';
    const atr  = r.atr  != null ? '\u20b9' + Number(r.atr).toFixed(1) : '—';
    // LTP cell — will be updated asynchronously
    const ltpId = `toast-ltp-${r.ticker}-${Date.now()}`;
    // Kick off async LTP fetch and inject into toast
    return `<div style="border-bottom:1px solid rgba(255,255,255,.07);padding:4px 0">
      <span style="color:var(--accent);font-weight:700">${r.ticker}</span>
      <span style="margin-left:6px;background:rgba(0,255,136,.12);color:var(--accent);
        border-radius:4px;padding:1px 6px;font-size:10px">${gr}</span>
      <span style="color:var(--text2);margin-left:4px;font-size:10px">${sig}</span><br>
      <span style="color:var(--text3)">Close: ${cls}&nbsp;&nbsp;Stop: ${sl}&nbsp;&nbsp;RSI: ${rsi}&nbsp;&nbsp;ATR: ${atr}</span><br>
      <span style="color:var(--text3);font-size:10px" id="${ltpId}">LTP: <em style="opacity:.5">loading…</em></span>
    </div>`;
  }).join('');

  const toast = document.getElementById('signalToast');
  document.getElementById('signalToastBody').innerHTML = lines;
  document.getElementById('signalToastTime').textContent =
    `\uD83D\uDCE1 Screened: ${idxLabel} \u00B7 ${now} IST \u00B7 ${top.length} signal${top.length > 1 ? 's' : ''} found`;

  const toastTickers = top.map(r => r.ticker).join(',');
  setTimeout(() => {
    fetch(`${API_BASE}/ltp/batch?tickers=${encodeURIComponent(toastTickers)}`)
      .then(res => res.json())
      .then(data => {
        const ltpMap = data.ltps || {};
        top.forEach(r => {
          const el = document.querySelector(`[id^="toast-ltp-${r.ticker}-"]`);
          if (!el) return;
          const ltp = ltpMap[r.ticker];
          if (ltp == null) { el.textContent = 'LTP: N/A'; return; }
          const diff = r.ltp_change_since_scan;
          const sign = diff != null ? (diff >= 0 ? '+' : '') : '';
          const diffStr = diff != null ? ` (${sign}${Number(diff).toFixed(2)})` : ' (—)';
          el.innerHTML = `LTP: <span style="color:${diff!=null&&diff>=0?'var(--accent)':'var(--red)'};">\u20b9${Number(ltp).toFixed(2)}${diffStr}</span>`;
        });
      })
      .catch(() => {});
  }, 200);

  toast.classList.remove('show');
  void toast.offsetWidth;          // force reflow so animation replays
  toast.classList.add('show');

  // Auto-close toast after 12 seconds
  setTimeout(closeToast, 12000);

  // ── Native OS Push Notification ───────────────────────────────────────────
  if (canPush) {
    top.forEach((r, i) => {
      const cls   = r.close != null ? '\u20b9' + Number(r.close).toFixed(2) : '';
      const sl    = r.stop_loss != null ? ' | Stop \u20b9' + Number(r.stop_loss).toFixed(2) : '';
      const score = r.total_score || 0;
      setTimeout(() => {
        new Notification(`${r.ticker} \u2014 ${r.signal}`, {
          body: `Grade ${r.grade} | Score ${score}\nClose ${cls}${sl}\nRSI ${r.rsi != null ? Number(r.rsi).toFixed(1) : '—'} | ATR ${r.atr != null ? '\u20b9'+Number(r.atr).toFixed(1) : '—'}`,
          icon:  '/static/img/favicon.png',
          tag:   `nse-${r.ticker}`,
          badge: '/static/img/favicon.png',
          requireInteraction: false
        });
      }, i * 800);   // stagger multi-notifs by 800 ms each
    });
  }
}

function closeToast() {
  const t = document.getElementById('signalToast');
  t.classList.remove('show');
  setTimeout(() => { t.style.display = 'none'; }, 300);
}


/* ═══════════════════════════════════════════════════════════════════════════
   SECTOR INTELLIGENCE MODULE
   ──────────────────────────────────────────────────────────────────────────
   Reads /api/sectors/summary + /api/sectors/nse-indices
   Renders heatmap and cards views
   Zero modification to existing screener code
═══════════════════════════════════════════════════════════════════════════ */

let _sectorCurrentView = 'cards';   // 'cards' is the only view now
let _sectorDataCache   = null;        // last fetched sector summary
let _sectorLoading     = false;

// ---------------------------------------------------------------------------
// Main entry — fetch both endpoints and render
// ---------------------------------------------------------------------------
async function loadSectorData(silent = false) {
  if (_sectorLoading) return;
  _sectorLoading = true;

  const cards     = document.getElementById('sectorCards');
  const emptyEl   = document.getElementById('sectorEmpty');
  const idxBar    = document.getElementById('nseIdxBar');
  const metaLabel = document.getElementById('sectorMetaLabel');

  if (!silent) {
    if (cards)    cards.innerHTML  = '<div style="color:var(--text3);font-family:var(--mono);font-size:10px;padding:20px">&#9783; Loading sector data…</div>';
    if (emptyEl)  emptyEl.style.display = 'none';
    if (idxBar)   idxBar.style.display  = 'none';
  }

  try {
    // Parallel fetch
    const [summaryResp, indicesResp] = await Promise.all([
      fetch('/api/sectors/summary'),
      fetch('/api/sectors/nse-indices'),
    ]);

    const summaryData  = await summaryResp.json();
    const indicesData  = await indicesResp.json();

    if (!summaryData.ok || !summaryData.sectors || !summaryData.sectors.length) {
      if (emptyEl)  emptyEl.style.display = 'block';
      if (metaLabel) metaLabel.textContent = '\u2015 SECTOR INTELLIGENCE — no screener data yet';
      _sectorLoading = false;
      return;
    }

    _sectorDataCache = summaryData.sectors;

    // Update meta label
    if (metaLabel) {
      const ts = summaryData.finished_at
        ? new Date(summaryData.finished_at).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'})
        : 'last run';
      metaLabel.textContent = `\u2015 SECTOR INTELLIGENCE \u00B7 ${summaryData.sectors.length} sectors \u00B7 ${summaryData.total_stocks || ''} stocks \u00B7 ${ts} IST`;
    }

    // Render NSE index bar
    if (indicesData.ok && indicesData.indices && indicesData.indices.length) {
      renderNseIndices(indicesData.indices);
    }

    // Render current view
    renderSectorView();

  } catch (err) {
    if (cards) cards.innerHTML = `<div style="color:var(--red);font-family:var(--mono);font-size:10px;padding:20px">\u26a0 Error loading sector data: ${err.message}</div>`;
  }

  _sectorLoading = false;
}

// ---------------------------------------------------------------------------
// NSE Index bar
// ---------------------------------------------------------------------------
function renderNseIndices(indices) {
  const bar = document.getElementById('nseIdxBar');
  if (!bar || !indices.length) return;

  bar.innerHTML = indices.map(idx => {
    const pct = idx.pct_change;
    const cls = pct > 0.1 ? 'pos' : pct < -0.1 ? 'neg' : 'flat';
    const sign = pct > 0 ? '+' : '';
    return `
      <div class="nse-idx-pill ${cls}" title="${idx.index}: \u20b9${idx.last_price}">
        <span class="nse-idx-name">${idx.display_name}</span>
        <span class="nse-idx-pct ${cls}">${sign}${pct.toFixed(2)}%</span>
      </div>`;
  }).join('');

  bar.style.display = 'flex';
}

// ---------------------------------------------------------------------------
// Render Sector View
// ---------------------------------------------------------------------------
function renderSectorView() {
  const cards = document.getElementById('sectorCards');
  if (cards) {
    cards.style.display = 'grid';
    renderSectorCards(_sectorDataCache);
  }
}

// ---------------------------------------------------------------------------
// Cards rendering
// ---------------------------------------------------------------------------
function gradeColor(g) {
  return g === 'A+' ? 'var(--accent)' : g === 'A' ? '#00cc78' : g === 'B' ? 'var(--warn)' : 'var(--text3)';
}

function renderSectorCards(sectors) {
  const el = document.getElementById('sectorCards');
  if (!el || !sectors) return;

  el.innerHTML = sectors.map(s => {
    const m       = s.momentum || 'WEAK';
    const mColor  = m === 'STRONG' ? '#00ff88' : m === 'MODERATE' ? '#ffb400' : '#ff5050';
    const rsLabel = s.avg_rs_nifty != null ? (s.avg_rs_nifty >= 1 ? '+' : '') +
                    ((s.avg_rs_nifty - 1) * 100).toFixed(1) + '%' : '\u2014';
    const rsColor = s.avg_rs_nifty != null ? (s.avg_rs_nifty >= 1 ? '#00ff88' : '#ff5050') : 'var(--text3)';

    const top3Html = (s.top3 || []).map((t, i) => {
      const gc = gradeColor(t.grade);
      return `
        <div class="sc-top3-row">
          <span style="color:var(--text3);font-family:var(--mono);font-size:8px">#${i+1}</span>
          <span class="sc-top3-ticker" onclick="openCpByTicker('${t.ticker}')" style="cursor:pointer">${t.ticker}</span>
          <span class="sc-top3-score">${t.score != null ? t.score.toFixed(1) : '\u2014'}</span>
          <span class="sc-top3-grade" style="background:${gc}18;color:${gc}">${t.grade || '?'}</span>
        </div>`;
    }).join('');

    const astStatus = s.astro_status || 'Neutral';
    const astCol    = astStatus === 'Upside' ? '#00ff88' : astStatus === 'Downside' ? '#ff5050' : '#ffb400';
    const astBg     = astStatus === 'Upside' ? 'rgba(0,255,136,.15)' : astStatus === 'Downside' ? 'rgba(255,80,80,.15)' : 'rgba(255,180,0,.15)';
    const astIcon   = astStatus === 'Upside' ? '\uD83D\uDCC8' : astStatus === 'Downside' ? '\uD83D\uDCC9' : '\u2796';

    return `
      <div class="sector-card">
        <div class="sc-header">
          <span class="sc-name">${s.display_name || s.sector}</span>
          <span class="hm-badge" style="background: ${astBg}; color: ${astCol}; border: 1px solid ${astBg}; text-transform: uppercase; font-size: 8px; letter-spacing: 0.05em; font-family: var(--mono)">ASTRO (${(s.ruling_planets || 'JUP').toUpperCase()})</span>
        </div>
        <div class="sc-stats" style="grid-template-columns: 1fr;">
          <div class="sc-stat">
            <div class="sc-stat-val" style="color:${astCol};font-size:13px;font-weight:700">${astIcon} ${astStatus}</div>
            <div class="sc-stat-lbl">ASTRO TRANSIT</div>
          </div>
        </div>
        ${top3Html ? `<div class="sc-top3">
          <div style="font-family:var(--mono);font-size:8px;color:var(--text3);letter-spacing:.06em;margin-bottom:4px">TOP PICKS</div>
          ${top3Html}
        </div>` : ''}
      </div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Filter screener table by sector when heatmap cell is clicked
// ---------------------------------------------------------------------------
function _filterScreenerBySector(sector) {
  // Switch to screener tab and apply a sector filter
  switchTab('screener');
  // If results are loaded, filter the table to show only this sector
  if (_screenerData && _screenerData.length) {
    const sectorRows = _screenerData.filter(r =>
      (r.sector || '').toLowerCase() === sector.toLowerCase()
    );
    if (sectorRows.length) {
      // Temporarily show only sector rows by setting a sector filter
      // (existing screener data is unchanged, just filtered for display)
      const container = document.getElementById('screenerTable');
      const na = () => '<span style="color:var(--text3);font-size:9px;opacity:.6">N/A</span>';
      const fmtN = (v, d) => (v != null && !isNaN(Number(v))) ? Number(v).toFixed(d) : null;

      container.innerHTML = `
        <div class="screener-count" style="display:flex;justify-content:space-between">
          <span>&#9783; ${sector} &mdash; ${sectorRows.length} stocks &nbsp;\u00B7&nbsp;
            <button onclick="renderScreenerTable()" style="background:none;border:none;color:var(--accent);cursor:pointer;font-family:var(--mono);font-size:10px;padding:0">&#8592; back to all</button>
          </span>
        </div>
        <div class="screener-tbl-wrap">
          <table class="screener-tbl">
            <thead><tr>
              <th>TICKER</th><th>SCORE</th><th>GRD</th><th>SIGNAL</th>
              <th>RSI</th><th>CLOSE \u20b9</th>
            </tr></thead>
            <tbody>
              ${sectorRows.sort((a,b) => (b.total_score||0)-(a.total_score||0)).map(r => {
                const sc    = r.total_score ?? 0;
                const scCol = sc>=70?'var(--accent)':sc>=55?'var(--warn)':'var(--red)';
                const gc    = r.grade==='A+'?'var(--accent)':r.grade==='A'?'#00cc78':r.grade==='B'?'var(--warn)':'var(--text3)';
                const sig   = (r.signal||'').includes('BUY')?'pill-buy':(r.signal||'').includes('WATCH')?'pill-watch':'pill-neutral';
                const rsi   = fmtN(r.rsi,1);
                 return `<tr onclick="openCpFromRow(event,'${r.ticker}','${r.sector||''}','${r.transit_status||'Neutral'}','${r.ruling_planets||'Jup'}',${r.astro_score||3})" title="Click to chart · Shift+click to analyse">
                  <td class="td-ticker">${r.ticker}</td>
                  <td class="td-score" style="color:${scCol}">${sc}</td>
                  <td><span style="color:${gc};font-weight:700">${r.grade||'?'}</span></td>
                  <td><span class="signal-pill ${sig}" style="padding:2px 8px;font-size:10px">${r.signal||'\u2014'}</span></td>
                  <td class="td-mono">${rsi!=null?rsi:na()}</td>
                  <td class="td-mono">${r.close!=null?'\u20b9'+Number(r.close).toFixed(2):na()}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    }
  }
}


let _lastNotifId = 0;
let _notifPollTimer = null;

function _startNotificationPolling() {
  clearInterval(_notifPollTimer);
  _pollNotifications();
  _notifPollTimer = setInterval(_pollNotifications, 15000); // poll every 15s
}

async function _pollNotifications() {
  try {
    const resp = await fetch(`/api/notifications?since_id=${_lastNotifId}`);
    const data = await resp.json();
    const list = data.notifications || [];
    if (list.length > 0) {
      _lastNotifId = Math.max(...list.map(n => n.id));
      _showInAppToast(list);
      if (_screenerMode === 'running' || _screenerMode === 'booked') {
        loadScreenerModeData();
      }
    }
  } catch (e) {
    // silently ignore network errors
  }
}

function _showInAppToast(notifications) {
  const toast = document.getElementById('signalToast');
  if (!toast) return;
  
  const html = notifications.map(n => {
    let titleColor = 'var(--accent)';
    let typeLabel = 'ALERT';
    if (n.type === 'sim_entry') {
      titleColor = '#00ff88';
      typeLabel = 'SIM ENTRY';
    } else if (n.type === 'booked') {
      titleColor = '#ffb400';
      typeLabel = 'BOOKED POSITION';
    }
    
    return `
      <div style="border-bottom:1px solid rgba(255,255,255,.07);padding:6px 0">
        <span style="color:${titleColor};font-weight:700;font-size:10px">${typeLabel}</span>
        <span style="color:var(--text1);margin-left:6px;font-weight:600">${n.ticker}</span><br>
        <span style="color:var(--text2);font-size:11px;line-height:1.4">${n.message}</span>
      </div>
    `;
  }).join('');
  
  document.getElementById('signalToastBody').innerHTML = html;
  
  const titleSpan = toast.querySelector('span');
  if (titleSpan) {
    titleSpan.innerHTML = '&#128276; SIMULATION NOTIFICATION';
  }
  
  document.getElementById('signalToastTime').textContent = 
    `Time: ${new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })} IST`;
    
  toast.classList.remove('show');
  void toast.offsetWidth;          // force reflow
  toast.classList.add('show');
  
  setTimeout(closeToast, 8000);
}
