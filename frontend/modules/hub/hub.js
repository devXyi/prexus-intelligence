/**
 * modules/hub/hub.js
 * Prexus Intelligence — Hub Module
 * THE GREAT FILE · Phase 2
 */

import { store } from '../../js/store.js';
import { getAssets } from '../../js/api.js';

export async function initHub() {
  const user = store.get('user');
  const org  = store.get('org');

  const orgNameEl = document.getElementById('hubOrgName');
  if (orgNameEl) orgNameEl.textContent = org?.orgName || user?.org_name || user?.email || '—';

  try {
    const assets = await getAssets();
    if (Array.isArray(assets)) {
      store.set('assets', assets);
      const countEl = document.getElementById('hubAssetCount');
      if (countEl) countEl.textContent = assets.length;
      const lastEl = document.getElementById('hubLastRun');
      if (lastEl && assets.length > 0) lastEl.textContent = new Date().toISOString().slice(11,16)+'Z';
    }
  } catch {
    const cached = store.get('assets') || [];
    const countEl = document.getElementById('hubAssetCount');
    if (countEl) countEl.textContent = cached.length;
  }
}

export function destroyHub() {}
