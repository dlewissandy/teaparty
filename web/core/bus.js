// Cross-feature event bus using EventTarget.
// Features never import from other features; they communicate through the bus.
//
// Usage:
//   bus.emit('chat:send', { content })
//   bus.on('chat:send', (detail) => { ... })  -> returns unsub fn

class EventBus {
  constructor() {
    this._target = new EventTarget();
  }

  /** Emit an event with optional detail data. */
  emit(name, detail = null) {
    this._target.dispatchEvent(new CustomEvent(name, { detail }));
  }

  /** Listen for an event. Returns an unsubscribe function. */
  on(name, fn) {
    const handler = (e) => fn(e.detail);
    this._target.addEventListener(name, handler);
    return () => this._target.removeEventListener(name, handler);
  }

  /** Listen for an event once. */
  once(name, fn) {
    const handler = (e) => fn(e.detail);
    this._target.addEventListener(name, handler, { once: true });
  }
}

export const bus = new EventBus();
