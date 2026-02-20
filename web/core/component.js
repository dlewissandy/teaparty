// Function-based component model.
//
// Components: (props) => { el, onMount?, onDestroy? }
// mount(container, componentFn, props) - insert, call onMount, store teardown
// html`<div>...` - tagged template to create DOM from HTML strings
// reconcileList(container, items, keyFn, createFn, updateFn) - keyed list diffing

const _teardowns = new WeakMap();

/**
 * Mount a component into a container. Returns a teardown function.
 */
export function mount(container, componentFn, props = {}) {
  // Teardown previous contents
  unmount(container);

  const result = componentFn(props);
  const el = result.el;
  container.innerHTML = '';
  container.appendChild(el);

  const teardowns = [];
  _teardowns.set(container, teardowns);

  if (result.onMount) {
    const cleanup = result.onMount();
    if (typeof cleanup === 'function') teardowns.push(cleanup);
  }

  if (result.onDestroy) {
    teardowns.push(result.onDestroy);
  }

  return () => unmount(container);
}

/**
 * Unmount a component from a container.
 */
export function unmount(container) {
  const teardowns = _teardowns.get(container);
  if (teardowns) {
    for (const fn of teardowns) {
      try { fn(); } catch (e) { console.error('Teardown error:', e); }
    }
    _teardowns.delete(container);
  }
}

/**
 * Tagged template literal for creating DOM elements from HTML.
 * Returns a DocumentFragment if multiple root elements, or a single Element.
 */
export function html(strings, ...values) {
  const raw = strings.reduce((acc, str, i) => {
    let val = values[i] !== undefined ? values[i] : '';
    if (Array.isArray(val)) val = val.join('');
    return acc + str + val;
  }, '');

  const tpl = document.createElement('template');
  tpl.innerHTML = raw.trim();
  const content = tpl.content;
  return content.childElementCount === 1 ? content.firstElementChild : content;
}

/**
 * Keyed list reconciliation - efficient DOM diffing for lists.
 *
 * @param {HTMLElement} container - parent element
 * @param {Array} items - data array
 * @param {Function} keyFn - (item) => unique key string
 * @param {Function} createFn - (item) => HTMLElement (create new DOM node)
 * @param {Function} updateFn - (el, item) => void (update existing DOM node)
 */
export function reconcileList(container, items, keyFn, createFn, updateFn) {
  const existingByKey = new Map();
  for (const child of Array.from(container.children)) {
    const key = child.dataset.key;
    if (key) existingByKey.set(key, child);
  }

  const newKeys = new Set();
  const fragment = document.createDocumentFragment();

  for (const item of items) {
    const key = String(keyFn(item));
    newKeys.add(key);

    let el = existingByKey.get(key);
    if (el) {
      updateFn(el, item);
    } else {
      el = createFn(item);
      el.dataset.key = key;
    }
    fragment.appendChild(el);
  }

  // Remove nodes no longer in the list
  for (const [key, el] of existingByKey) {
    if (!newKeys.has(key)) {
      el.remove();
    }
  }

  container.innerHTML = '';
  container.appendChild(fragment);
}
