// Proxy-based reactive store with batched notifications via queueMicrotask.
//
// Usage:
//   const store = createStore(initialState)
//   store.get()           -> read-only state reference
//   store.update(fn)      -> mutate state, auto-notify subscribers
//   store.on(path, fn)    -> subscribe to changes at path prefix, returns unsub fn

export function createStore(initial) {
  const state = structuredClone(initial);
  const subscribers = new Map(); // path -> Set<fn>
  let changedPaths = new Set();
  let flushScheduled = false;

  function flush() {
    flushScheduled = false;
    const paths = changedPaths;
    changedPaths = new Set();
    for (const [prefix, fns] of subscribers) {
      for (const p of paths) {
        if (p === prefix || p.startsWith(prefix + '.') || prefix.startsWith(p + '.') || prefix === '*') {
          for (const fn of fns) {
            try { fn(state); } catch (e) { console.error('Store subscriber error:', e); }
          }
          break;
        }
      }
    }
  }

  function markChanged(path) {
    changedPaths.add(path);
    if (!flushScheduled) {
      flushScheduled = true;
      queueMicrotask(flush);
    }
  }

  function makePath(segments) {
    return segments.join('.');
  }

  function createProxy(obj, segments) {
    if (obj === null || typeof obj !== 'object') return obj;
    return new Proxy(obj, {
      set(target, prop, value) {
        const old = target[prop];
        if (old === value) return true;
        target[prop] = value;
        markChanged(makePath([...segments, prop]));
        return true;
      },
      get(target, prop) {
        const val = target[prop];
        if (val !== null && typeof val === 'object' && !Array.isArray(val)) {
          return createProxy(val, [...segments, prop]);
        }
        return val;
      },
      deleteProperty(target, prop) {
        delete target[prop];
        markChanged(makePath([...segments, prop]));
        return true;
      },
    });
  }

  const proxy = createProxy(state, []);

  return {
    /** Read-only state reference (mutations go through update()) */
    get() { return state; },

    /** Mutate state. The function receives a proxy that tracks changes. */
    update(fn) {
      fn(proxy);
    },

    /** Subscribe to changes at a path prefix. Returns an unsubscribe function. */
    on(path, fn) {
      if (!subscribers.has(path)) subscribers.set(path, new Set());
      subscribers.get(path).add(fn);
      return () => {
        const set = subscribers.get(path);
        if (set) {
          set.delete(fn);
          if (set.size === 0) subscribers.delete(path);
        }
      };
    },

    /** Force-notify all subscribers for a path (e.g. after array mutation). */
    notify(path) {
      markChanged(path);
    },
  };
}
