export const SANDBOX_DENIED_CALLS = ["fetch", "WebSocket", "EventSource", "XMLHttpRequest", "Worker", "SharedWorker",
  "BroadcastChannel"];
export const SANDBOX_DENIED_STORAGE = ["indexedDB", "caches"];
const DEFAULT_TARGET = {};

/** Replace both direct and inherited browser capabilities. Web IDL APIs such as fetch and IndexedDB live on
 * WorkerGlobalScope.prototype, so shadowing only globalThis leaves their original descriptors recoverable.
 * @param {object} target */
export function denySandboxNetwork(target = DEFAULT_TARGET) {
  if (target === DEFAULT_TARGET) target = globalThis;
  const denied = () => { throw new TypeError("Network and storage access are disabled in the browser sandbox"); };
  /** @type {Map<string, PropertyDescriptor>} */
  const replacements = new Map();
  for (const name of SANDBOX_DENIED_CALLS) {
    replacements.set(name, { value: denied, writable: false, configurable: false });
  }
  for (const name of SANDBOX_DENIED_STORAGE) replacements.set(name, { get: denied, configurable: false });
  for (const [name, replacement] of replacements) {
    const owners = new Set([target]);
    for (let owner = target; owner; owner = Object.getPrototypeOf(owner)) {
      if (Object.prototype.hasOwnProperty.call(owner, name)) owners.add(owner);
    }
    for (const owner of owners) {
      try {
        Object.defineProperty(owner, name, replacement);
      } catch (error) {
        throw new TypeError(`Cannot disable browser sandbox capability ${name}`, { cause: error });
      }
    }
  }
}
