// Serves the built site (web/dist) like GitHub Pages: static files only, no /api, so the page runs in browser mode.
import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../dist/", import.meta.url));
const types = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".whl": "application/octet-stream", ".wasm": "application/wasm", ".svg": "image/svg+xml",
};
createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1:4175");
  const relative = url.pathname === "/" ? "index.html" : decodeURIComponent(url.pathname.slice(1));
  const path = normalize(join(root, relative));
  try {
    if (!path.startsWith(root)) throw new Error("outside");
    const size = statSync(path).size;
    response.writeHead(200, { "content-type": types[extname(path)] ?? "application/octet-stream", "content-length": size });
    createReadStream(path).pipe(response);
  } catch {
    response.writeHead(404).end();
  }
}).listen(4175, "127.0.0.1");
