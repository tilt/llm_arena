// Drive headless Chrome over the DevTools protocol: open a page, wait until document.title === "done", print #log.
import { spawn } from "node:child_process";
const url = process.argv[2];
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new", "--disable-gpu", "--remote-debugging-port=9333", "--user-data-dir=/tmp/arena-spike-chrome", "about:blank"],
  { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets;
for (let i = 0; i < 50; i++) { try { targets = await (await fetch("http://127.0.0.1:9333/json")).json(); break; } catch { await sleep(200); } }
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); } };
const send = (method, params = {}) => new Promise((r) => { pending.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true })).result.value;
await send("Page.navigate", { url });
const deadline = Date.now() + 600000;
while (Date.now() < deadline) {
  await sleep(2000);
  if ((await evaluate("document.title")) === "done") break;
}
console.log(await evaluate("document.getElementById('log')?.textContent"));
ws.close(); chrome.kill();
