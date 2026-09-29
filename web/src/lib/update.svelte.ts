// A tab keeps running the UI it loaded. After an upgrade it would talk to a newer server with old code (and send
// requests the server no longer understands). Every build writes version.json; when it no longer matches the build
// this tab runs, the app offers a reload.
// `checked`: version.json was read, so a mismatch with the server's build means the server is the older one.
export const update = $state({ available: false, checked: false });

let lastCheck = 0;

async function check(): Promise<void> {
  if (update.available || Date.now() - lastCheck < 30_000) return;
  lastCheck = Date.now();
  try {
    const response = await fetch(new URL("version.json", document.baseURI), { cache: "no-store" });
    if (!response.ok) return; // the dev server has no version file
    const { build } = (await response.json()) as { build?: string };
    if (build && build !== __BUILD_ID__) update.available = true;
    update.checked = true;
  } catch { /* offline or not JSON: try again later */ }
}

/** The local server started before this page's build (the page is current: the server needs a restart). */
export function serverIsOlder(serverBuild: string | undefined): boolean {
  return update.checked && !update.available && !!serverBuild && serverBuild !== __BUILD_ID__;
}

/** Check now, whenever the tab comes back into view, and every few minutes. Returns the cleanup. */
export function watchUpdates(): () => void {
  const onVisible = () => { if (document.visibilityState === "visible") void check(); };
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("focus", onVisible);
  const timer = setInterval(() => void check(), 5 * 60_000);
  void check();
  return () => {
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("focus", onVisible);
    clearInterval(timer);
  };
}
