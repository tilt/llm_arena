const EXPECTED = {
  "/sandbox-bootstrap.js": "8b8ebc4c0cb3dc7fdd9b3d0b703ec88fb951598dfd645cd97a49a192e5bba922",
  "/runtime.bin": "b425224227eeadcaf5ca994dd3b7e3a13d2313213123bc692501927ff377c26c",
  "/package.whl": "447afc318a51f5f7aafafc6449cdb20be481ec5163fb48c9280d0e5543f4e704",
};

const hex = (buffer) => Array.from(new Uint8Array(buffer))
  .map((byte) => byte.toString(16).padStart(2, "0")).join("");

async function verified(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`fixture fetch failed: ${path}`);
  const bytes = await response.arrayBuffer();
  const actual = hex(await crypto.subtle.digest("SHA-256", bytes));
  if (actual !== EXPECTED[path]) throw new Error(`fixture digest mismatch: ${path}`);
  return bytes;
}

window.__isolationAudit = { verifiedBeforeIframe: false, rejectedMessages: 0, iframeLoaded: false, messages: [], errors: [] };
addEventListener("error", (event) => window.__isolationAudit.errors.push(String(event.message)));
addEventListener("unhandledrejection", (event) => window.__isolationAudit.errors.push(String(event.reason)));
window.__spikeResult = (async () => {
  const [bootstrap, runtimeBytes, packageBytes] = await Promise.all([
    verified("/sandbox-bootstrap.js"), verified("/runtime.bin"), verified("/package.whl"),
  ]);
  const requestId = crypto.randomUUID();
  void bootstrap;
  window.__isolationAudit.verifiedBeforeIframe = true;
  window.__isolationAudit.bootstrapMechanism = "external-sri+csp-hash";
  const iframe = document.createElement("iframe");
  iframe.sandbox = "allow-scripts";
  iframe.srcdoc = `<!doctype html><meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; script-src 'sha256-i468TAyz3H/dmz0LcD7Ij7lRWY39ZFzZekmhkuW7qSI=' 'wasm-unsafe-eval';
      worker-src blob:; connect-src 'none';
      img-src 'none'; style-src 'none'; base-uri 'none'; form-action 'none'">
    <script src="http://127.0.0.1:4174/sandbox-bootstrap.js?requestId=${encodeURIComponent(requestId)}"
      integrity="sha256-i468TAyz3H/dmz0LcD7Ij7lRWY39ZFzZekmhkuW7qSI=" crossorigin="anonymous"><\/script>`;
  iframe.onload = () => { window.__isolationAudit.iframeLoaded = true; };
  document.body.append(iframe);

  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("isolation spike timed out")), 12_000);
    addEventListener("message", function receive(event) {
      const data = event.data;
      const sourceMatches = event.source === iframe.contentWindow;
      if (sourceMatches) window.__isolationAudit.messages.push({ origin: event.origin, keys: Object.keys(event.data ?? {}).sort() });
      const base = sourceMatches && event.origin === "null" && data?.version === 1 && data.requestId === requestId;
      if (base && data.kind === "spike-ready"
          && Object.keys(data).sort().join(",") === "kind,requestId,version") {
        iframe.contentWindow.postMessage({
          kind: "verified-assets", version: 1, requestId,
          runtimeBytes, packageBytes,
          expected: [EXPECTED["/runtime.bin"], EXPECTED["/package.whl"]],
        }, "*", [runtimeBytes, packageBytes]);
        return;
      }
      if (base && data.kind === "spike-result"
          && Object.keys(data).sort().join(",") === "kind,requestId,result,version") {
        clearTimeout(timer);
        removeEventListener("message", receive);
        resolve(data.result);
        return;
      }
      if (sourceMatches) window.__isolationAudit.rejectedMessages += 1;
    });
  });
})();
