import { createReadStream, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("./fixtures/", import.meta.url));
const lockdown = fileURLToPath(new URL("../../src/engine/sandbox-lockdown.ts", import.meta.url));
const hits = [];
const types = { ".html": "text/html", ".js": "text/javascript", ".bin": "application/octet-stream", ".whl": "application/octet-stream" };
const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1:4174");
  if (url.pathname.startsWith("/canary")) {
    hits.push(url.pathname);
    response.writeHead(204, { "Access-Control-Allow-Origin": "*" });
    response.end();
    return;
  }
  if (url.pathname === "/hits") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(hits));
    return;
  }
  if (url.pathname === "/sandbox-lockdown.ts") {
    const size = statSync(lockdown).size;
    response.writeHead(200, { "content-type": "text/javascript", "content-length": size, "cache-control": "no-store" });
    createReadStream(lockdown).pipe(response);
    return;
  }
  const relative = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
  const path = normalize(join(root, relative));
  if (!path.startsWith(root)) {
    response.writeHead(404).end();
    return;
  }
  try {
    const size = statSync(path).size;
    response.writeHead(200, {
      "content-type": types[extname(path)] ?? "application/octet-stream",
      "content-length": size,
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    });
    createReadStream(path).pipe(response);
  } catch {
    response.writeHead(404).end();
  }
});
server.on("upgrade", (request, socket) => {
  hits.push(new URL(request.url ?? "/", "http://127.0.0.1:4174").pathname);
  socket.destroy();
});
server.listen(4174, "127.0.0.1", () => process.stdout.write("isolation spike ready\n"));
