/**
 * js/router.js
 * Prexus Intelligence — Page Router
 * THE GREAT FILE · Phase 1
 *
 * Controls which page is visible.
 * Handles enter/exit animations.
 * Modules call navigate() to change pages.
 * Never touches module-specific logic.
 */

import { store } from './store.js';
import { $ } from './utils.js';

/* ── Valid pages ──────────────────────────────────────────── */
const PAGES = ['auth', 'org', 'hub', 'meteorium'];

/* ── Navigate to a page ───────────────────────────────────── */

/**
 * Navigate to a page with smooth transition.
 * @param {string} pageId - one of: 'auth' | 'org' | 'hub' | 'meteorium'
 */
export function navigate(pageId) {
  if (!PAGES.includes(pageId)) {
    console.error(`[router] Unknown page: "${pageId}"`);
    return;
  }

  const current = document.querySelector('.page.active');
  const next    = document.getElementById(`page-${pageId}`);

  if (!next) {
    console.error(`[router] Page element not found: #page-${pageId}`);
    return;
  }

  // Already on this page
  if (current === next) return;

  const activate = () => {
    // Hide all pages
    document.querySelectorAll('.page').forEach(p => {
      p.classList.remove('active', 'page-exit');
      p.style.display = '';
    });

    // Special case: meteorium uses display:flex via CSS
    // All others use display:flex from .page.active
    next.classList.add('active');

    // Update store
    store.set('page', pageId);
  };

  if (current) {
    current.classList.add('page-exit');
    setTimeout(activate, 220);
  } else {
    activate();
  }
}

/**
 * Get current page ID.
 */
export function currentPage() {
  return store.get('page') || 'auth';
}

