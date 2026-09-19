/**
 * Single-slot registry for the currently spawned adapter relay child.
 * Shared so SIGINT/SIGTERM can kill either Pi or Cursor without importing
 * a live binding from a specific adapter module.
 *
 * No cleanup logic: the slot is overwritten by the next spawn.
 */

let activeAdapterChild = null;

export function setActiveAdapterChild(child) {
  activeAdapterChild = child;
}

export function getActiveAdapterChild() {
  return activeAdapterChild;
}
