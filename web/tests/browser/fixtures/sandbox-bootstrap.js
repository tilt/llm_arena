(() => {
  "use strict";
  const current = document.currentScript?.src ?? "";
  const requestId = new URL(current).searchParams.get("requestId") ?? "";
  const target = "http://127.0.0.1:4174/canary";
  const websocketTarget = "ws://127.0.0.1:4174/canary-websocket";
  const violations = [];
  document.addEventListener("securitypolicyviolation", (event) => violations.push(event.violatedDirective));

  const blocked = async (operation, timeoutMs = 1200) => {
    try {
      return await Promise.race([
        operation().then(() => false, () => true),
        new Promise((resolve) => setTimeout(() => resolve(true), timeoutMs)),
      ]);
    } catch {
      return true;
    }
  };

  const socketBlocked = (make) => blocked(() => new Promise((resolve, reject) => {
    const socket = make();
    socket.onopen = () => { socket.close(); resolve(); };
    socket.onerror = () => { socket.close(); reject(new Error("blocked")); };
  }));

  const workerProbe = () => new Promise((resolve, reject) => {
    const source = `
      const target = ${JSON.stringify(target)};
      const websocketTarget = ${JSON.stringify(websocketTarget)};
      const blocked = async (operation, timeoutMs = 1200) => {
        try { return await Promise.race([operation().then(() => false, () => true),
          new Promise(resolve => setTimeout(() => resolve(true), timeoutMs))]); }
        catch { return true; }
      };
      const socketBlocked = () => blocked(() => new Promise((resolve, reject) => {
        const socket = new WebSocket(websocketTarget);
        socket.onopen = () => { socket.close(); resolve(); };
        socket.onerror = () => { socket.close(); reject(new Error("blocked")); };
      }));
      const eventSourceBlocked = () => blocked(() => new Promise((resolve, reject) => {
        const source = new EventSource(target + "/events");
        source.onopen = () => { source.close(); resolve(); };
        source.onerror = () => { source.close(); reject(new Error("blocked")); };
      }));
      const storageBlocked = (name) => {
        try { globalThis[name].setItem("arena-spike", "no"); return false; } catch { return true; }
      };
      (async () => self.postMessage({
        fetch: await blocked(() => fetch(target)),
        websocket: await socketBlocked(),
        eventSource: await eventSourceBlocked(),
        importScripts: await blocked(() => Promise.resolve().then(() => importScripts(target + "/script.js"))),
        dynamicImport: await blocked(() => import(target + "/module.js")),
        localStorage: storageBlocked("localStorage"),
        sessionStorage: storageBlocked("sessionStorage"),
      }))();`;
    const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
    const worker = new Worker(url);
    worker.onmessage = (event) => { worker.terminate(); URL.revokeObjectURL(url); resolve(event.data); };
    worker.onerror = (event) => { worker.terminate(); URL.revokeObjectURL(url); reject(new Error(event.message)); };
  });

  const storageBlocked = (name) => {
    try { window[name].setItem("arena-spike", "no"); return false; } catch { return true; }
  };

  const digest = async (buffer) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", buffer)))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");

  // Deliberately malformed: the parent must reject it before accepting the strict ready message.
  parent.postMessage({ kind: "spike-ready", requestId, extra: true }, "*");
  parent.postMessage({ kind: "spike-ready", version: 1, requestId }, "*");

  addEventListener("message", async (event) => {
    const data = event.data;
    if (event.source !== parent || event.origin !== "http://127.0.0.1:4174"
        || data?.kind !== "verified-assets" || data.version !== 1 || data.requestId !== requestId
        || Object.keys(data).sort().join(",") !== "expected,kind,packageBytes,requestId,runtimeBytes,version"
        || !(data.runtimeBytes instanceof ArrayBuffer) || !(data.packageBytes instanceof ArrayBuffer)
        || !Array.isArray(data.expected) || data.expected.length !== 2) return;
    const result = {
      opaqueOrigin: origin === "null",
      localStorage: storageBlocked("localStorage"),
      sessionStorage: storageBlocked("sessionStorage"),
      fetch: await blocked(() => fetch(target)),
      websocket: await socketBlocked(() => new WebSocket(websocketTarget)),
      eventSource: await socketBlocked(() => new EventSource(target + "/events")),
      dynamicImport: await blocked(() => import(target + "/module.js")),
      worker: await workerProbe(),
      assetDigests: [await digest(data.runtimeBytes), await digest(data.packageBytes)],
      expectedDigests: data.expected,
      violations,
    };
    parent.postMessage({ kind: "spike-result", version: 1, requestId, result }, "*");
  }, { once: true });
})();
