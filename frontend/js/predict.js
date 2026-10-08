/**
 * js/predict.js
 * Prexus Intelligence — Predictive Trajectory Engine
 *
 * Turns static risk scores into forward-looking intelligence:
 *   "Asset X will cross CRITICAL threshold in 3.2 days (87% exceedance probability, uncalibrated)"
 *
 * Pure math — no ML framework. Uses:
 *   - Exponential weighted moving average for trend
 *   - Baseline volatility from hand-set seasonal factors (illustrative, uncalibrated)
 *   - Monte Carlo projection (JS, 1000 draws, runs in ~2ms)
 */

import { store } from './store.js';

/* ══════════════════════════════════════════════════════════
   SEASONAL RISK DRIFT - ILLUSTRATIVE, hand-set values
   NOT derived from IPCC AR6 (v1 attributed these numbers to AR6 WG-II Ch.11); replace with fitted seasonality
══════════════════════════════════════════════════════════ */
const SEASONAL = {
  // month (0-11) → physical risk drift rate per day
  // Peak amplification in NH summer / SH summer
  physical: [0.0008, 0.0006, 0.0005, 0.0004, 0.0003, 0.0010,
             0.0014, 0.0013, 0.0009, 0.0005, 0.0006, 0.0009],
  // Transition risk drifts faster near Q1/Q4 (policy cycles)
  transition: [0.0012, 0.0010, 0.0008, 0.0006, 0.0005, 0.0004,
               0.0004, 0.0005, 0.0007, 0.0009, 0.0011, 0.0013],
};

const THRESHOLDS = {
  CRITICAL: 0.85,
  HIGH:     0.65,
  ELEVATED: 0.45,
};

/* ══════════════════════════════════════════════════════════
   CORE: Monte Carlo trajectory projection
══════════════════════════════════════════════════════════ */

/**
 * Project a risk score forward N days using stochastic drift.
 * Returns full distribution at each checkpoint.
 *
 * @param {number} score    - current risk 0–1
 * @param {number} drift    - daily drift rate (positive = worsening)
 * @param {number} vol      - daily volatility
 * @param {number} days     - projection horizon
 * @param {number} n        - MC draws (default 1000 — runs in ~2ms)
 * @returns {{ p10, p25, p50, p75, p90 }[]} percentiles per day
 */
function _mcProject(score, drift, vol, days, n = 1000) {
  const checkpoints = [1, 3, 7, 14, 30].filter(d => d <= days);
  const results = {};

  // Initialize paths
  const paths = Array.from({ length: n }, () => score);

  let day = 0;
  for (const checkpoint of checkpoints) {
    // Advance paths day by day
    while (day < checkpoint) {
      for (let i = 0; i < n; i++) {
        // Geometric Brownian motion with mean reversion above 0.9
        const z     = _randn();
        const mr    = paths[i] > 0.9 ? -(paths[i] - 0.9) * 0.05 : 0; // pull back if extreme
        paths[i]    = Math.max(0.01, Math.min(0.99, paths[i] + drift + vol * z + mr));
      }
      day++;
    }

    const sorted = [...paths].sort((a, b) => a - b);
    results[checkpoint] = {
      day:  checkpoint,
      p10:  sorted[Math.floor(n * 0.10)],
      p25:  sorted[Math.floor(n * 0.25)],
      p50:  sorted[Math.floor(n * 0.50)],
      p75:  sorted[Math.floor(n * 0.75)],
      p90:  sorted[Math.floor(n * 0.90)],
    };
  }

  return Object.values(results);
}

/** Box-Muller transform for normal random variate */
function _randn() {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/* ══════════════════════════════════════════════════════════
   MAIN: Compute trajectory for a single asset
══════════════════════════════════════════════════════════ */

/**
 * Compute full predictive trajectory for an asset.
 *
 * @param {object} asset  - asset from store
 * @returns {TrajectoryResult}
 */
export function computeTrajectory(asset) {
  const month = new Date().getMonth();
  const cr    = asset.cr ?? 0.5;
  const pr    = asset.pr ?? 0.5;
  const tr    = asset.tr ?? 0.5;

  // Seasonal drift rates
  const prDrift  = SEASONAL.physical[month]   * (1 + pr * 0.5);   // higher base = faster drift
  const trDrift  = SEASONAL.transition[month] * (1 + tr * 0.3);
  const crDrift  = prDrift * 0.6 + trDrift * 0.4;                 // composite weighted

  // Volatility: higher risk = higher vol (fat tails)
  const vol = 0.008 + cr * 0.012;

  // Project forward
  const projection = _mcProject(cr, crDrift, vol, 30);

  // Find threshold crossings (when does P50 cross each level?)
  const crossings = {};
  let prevP50 = cr;
  for (const { day, p50 } of projection) {
    for (const [name, threshold] of Object.entries(THRESHOLDS)) {
      if (!crossings[name] && prevP50 < threshold && p50 >= threshold) {
        crossings[name] = { day, confidence: _crossingConfidence(projection, day, threshold) };
      }
    }
    prevP50 = p50;
  }

  // 7-day trend signal
  const d7    = projection.find(p => p.day === 7);
  const delta7 = d7 ? d7.p50 - cr : crDrift * 7;
  const trend  = delta7 > 0.03 ? 'WORSENING' : delta7 < -0.02 ? 'IMPROVING' : 'STABLE';

  // Next threshold the asset will cross
  const currentBand  = _band(cr);
  const nextThreshold = _nextThreshold(cr);
  const crossing      = crossings[nextThreshold.name];

  return {
    current:         cr,
    trend,
    delta7:          Math.round(delta7 * 1000) / 1000,
    projection,
    crossings,
    nextCrossing:    crossing ? {
      threshold:   nextThreshold.name,
      level:       nextThreshold.value,
      days:        crossing.day,
      confidence:  crossing.confidence,
      probability: crossing.confidence,
    } : null,
    currentBand,
    drift:           Math.round(crDrift * 100000) / 100000,
    volatility:      Math.round(vol * 1000) / 1000,
    computed_at:     new Date().toISOString(),
  };
}

function _crossingConfidence(projection, day, threshold) {
  const snap = projection.find(p => p.day === day);
  if (!snap) return 0;
  // P(risk >= threshold): linear interpolation of the CDF through the stored percentiles,
  // anchored at the support edges (risk scores live in [0,1]). v1 returned hard-coded 0.85/0.70/...
  // buckets and printed them as "% confidence". This remains an UNCALIBRATED heuristic projection.
  const pts = [[0, 0], [snap.p10, 0.10], [snap.p25, 0.25], [snap.p50, 0.50], [snap.p75, 0.75], [snap.p90, 0.90], [1, 1]]
    .filter(([v]) => Number.isFinite(v)).sort((a, b) => a[0] - b[0]);
  if (threshold <= 0) return 1;
  if (threshold >= 1) return 0;
  for (let i = 1; i < pts.length; i++) {
    const [v0, f0] = pts[i - 1], [v1, f1] = pts[i];
    if (threshold <= v1) {
      const f = v1 === v0 ? f1 : f0 + (f1 - f0) * (threshold - v0) / (v1 - v0);
      return Math.min(1, Math.max(0, 1 - f));
    }
  }
  return 0;
}

function _band(score) {
  if (score >= 0.85) return 'CRITICAL';
  if (score >= 0.65) return 'HIGH';
  if (score >= 0.45) return 'ELEVATED';
  if (score >= 0.25) return 'MODERATE';
  return 'LOW';
}

function _nextThreshold(score) {
  if (score < 0.45) return { name: 'ELEVATED', value: 0.45 };
  if (score < 0.65) return { name: 'HIGH',     value: 0.65 };
  if (score < 0.85) return { name: 'CRITICAL', value: 0.85 };
  return { name: 'CRITICAL', value: 0.85 }; // already at max
}

/* ══════════════════════════════════════════════════════════
   PORTFOLIO INTELLIGENCE
══════════════════════════════════════════════════════════ */

/**
 * Compute trajectories for all assets and surface the most critical insights.
 * Returns sorted list of assets with their trajectories + key portfolio signals.
 */
export function computePortfolioIntelligence(assets) {
  if (!assets.length) return { assets: [], signals: [], overallTrend: 'STABLE' };

  const scored = assets.map(a => ({
    asset:      a,
    trajectory: computeTrajectory(a),
  }));

  // Sort: imminent crossings first, then by risk
  scored.sort((a, b) => {
    const aC = a.trajectory.nextCrossing?.days ?? 999;
    const bC = b.trajectory.nextCrossing?.days ?? 999;
    if (aC !== bC) return aC - bC;
    return (b.asset.cr ?? 0) - (a.asset.cr ?? 0);
  });

  // Portfolio-level signals
  const signals = [];

  const worsening = scored.filter(s => s.trajectory.trend === 'WORSENING');
  if (worsening.length > 0) {
    signals.push({
      type:    'TREND',
      level:   worsening.length >= assets.length * 0.5 ? 'HIGH' : 'ELEVATED',
      message: `${worsening.length} of ${assets.length} assets on worsening trajectory`,
      assets:  worsening.slice(0, 3).map(s => s.asset.id),
    });
  }

  const imminent = scored.filter(s => s.trajectory.nextCrossing?.days <= 7);
  if (imminent.length > 0) {
    signals.push({
      type:    'CROSSING',
      level:   'CRITICAL',
      message: `${imminent.length} asset${imminent.length > 1 ? 's' : ''} approaching threshold breach within 7 days`,
      assets:  imminent.map(s => s.asset.id),
    });
  }

  // Portfolio trend
  const worseCount = worsening.length;
  const overallTrend = worseCount > assets.length * 0.5 ? 'WORSENING'
    : worseCount < assets.length * 0.2 ? 'STABLE' : 'MIXED';

  return { assets: scored, signals, overallTrend };
}

/* ══════════════════════════════════════════════════════════
   BACKGROUND SCHEDULER
   Runs trajectories silently every 5 min and updates store
══════════════════════════════════════════════════════════ */

let _schedTimer = null;

export function startPredictionScheduler() {
  _runPredictions();
  _schedTimer = setInterval(_runPredictions, 5 * 60 * 1000);
}

export function stopPredictionScheduler() {
  if (_schedTimer) { clearInterval(_schedTimer); _schedTimer = null; }
}

function _runPredictions() {
  const assets = store.get('assets') || [];
  if (!assets.length) return;

  const intel = computePortfolioIntelligence(assets);
  store.set('portfolioIntelligence', intel);

  // Cache individual trajectories
  intel.assets.forEach(({ asset, trajectory }) => {
    store.patch('riskCache', {
      [asset.id]: {
        ...(store.get('riskCache')?.[asset.id] || {}),
        trajectory,
        ts: Date.now(),
      }
    });
  });
}

