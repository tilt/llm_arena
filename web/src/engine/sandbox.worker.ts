/// <reference lib="webworker" />
// Runs model-written Python in its own Pyodide, away from the engine. The engine terminates this
// worker on timeout (and starts a fresh one), which is the browser's equivalent of killing a process.
import { loadPyodide, type Pyodide } from "./pyodide";
import { validateSandboxRequest, type SandboxReply } from "./sandbox-protocol";

let py: Pyodide | null = null;

const EXEC = String.raw`
import base64, contextlib, glob, io, json, os, runpy, shutil, stat, sys, tempfile, traceback

MAX_STREAM_BYTES = 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_WORKDIR_BYTES = 100 * 1024 * 1024

class OutputLimit(Exception):
    pass

class LimitedIO(io.StringIO):
    def __init__(self):
        super().__init__()
        self.size = 0

    def write(self, value):
        encoded = value.encode("utf-8")
        remaining = MAX_STREAM_BYTES - self.size
        if remaining > 0:
            kept = encoded[:remaining].decode("utf-8", "ignore")
            super().write(kept)
            self.size += len(kept.encode("utf-8"))
        if len(encoded) > remaining:
            raise OutputLimit()
        return len(value)

def safe_name(name):
    parts = name.split("/")
    return (name and "\\" not in name and not os.path.isabs(name)
            and not (len(parts[0]) >= 2 and parts[0][1] == ":")
            and all(part not in ("", ".", "..") for part in parts)
            and not any(ord(char) < 32 or ord(char) == 127 for char in name))

def safe_read(path):
    if os.path.islink(path):
        raise ValueError("symlinks are not collected")
    current = os.path.dirname(path)
    while current and current != ".":
        if os.path.islink(current):
            raise ValueError("symlinks are not collected")
        current = os.path.dirname(current)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("not a regular file")
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            return handle.read(MAX_FILE_BYTES + 1)
    finally:
        os.close(descriptor)

def workdir_too_large(root):
    total = 0
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not os.path.islink(os.path.join(current, name))]
        for name in names:
            path = os.path.join(current, name)
            try:
                info = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > MAX_WORKDIR_BYTES:
                    return True
    return False

def arena_exec(code, files_json, collect_json):
    workdir = tempfile.mkdtemp(prefix="arena-")
    previous = os.getcwd()
    out, err, returncode = LimitedIO(), LimitedIO(), 0
    collected, omitted, output_truncated = {}, {}, False
    try:
        for name, b64 in json.loads(files_json).items():
            if not safe_name(name):
                raise ValueError(f"invalid sandbox file name: {name!r}")
            path = os.path.join(workdir, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(b64))
        with open(os.path.join(workdir, "main.py"), "w") as handle:
            handle.write(code)
        for name, module in list(sys.modules.items()):
            if (getattr(module, "__file__", "") or "").startswith(tempfile.gettempdir()):
                del sys.modules[name]
        os.chdir(workdir)
        sys.path.insert(0, workdir)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    runpy.run_path("main.py", run_name="__main__")
                except SystemExit as exc:
                    returncode = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
                except BaseException:
                    traceback.print_exc()
                    returncode = 1
        except OutputLimit:
            returncode, output_truncated = 1, True
        if "matplotlib.pyplot" in sys.modules:
            sys.modules["matplotlib.pyplot"].close("all")
        if workdir_too_large(workdir):
            omitted["<workdir>"] = f"work directory exceeds {MAX_WORKDIR_BYTES} bytes"
        else:
            total = 0
            for pattern in json.loads(collect_json):
                for path in glob.glob(pattern):
                    if path in collected or path in omitted:
                        continue
                    try:
                        content = safe_read(path)
                        if total + len(content) > MAX_TOTAL_BYTES:
                            raise ValueError(f"execution artifacts exceed {MAX_TOTAL_BYTES} bytes")
                        collected[path] = base64.b64encode(content).decode("ascii")
                        total += len(content)
                    except (OSError, ValueError) as exc:
                        omitted[path] = str(exc) if isinstance(exc, ValueError) else "not a safe regular file"
        return json.dumps({"stdout": out.getvalue()[-8000:], "stderr": err.getvalue()[-8000:],
                           "returncode": returncode, "timed_out": False, "files": collected,
                           "omitted": omitted, "output_truncated": output_truncated})
    finally:
        os.chdir(previous)
        if workdir in sys.path:
            sys.path.remove(workdir)
        shutil.rmtree(workdir, ignore_errors=True)
`;

self.onmessage = async (event: MessageEvent<unknown>) => {
  let requestId = "unknown-request";
  try {
    if (event.currentTarget !== self) throw new Error("invalid sandbox request source");
    const request = validateSandboxRequest(event.data);
    requestId = request.requestId;
    if (request.kind === "init") {
      const started = performance.now();
      py = await loadPyodide({ sandbox: true });
      await py.runPythonAsync(`import os\nos.environ["MPLBACKEND"] = "Agg"\n${EXEC}`);
      const networkIsolation = await networkSelfCheck();
      const reply: SandboxReply = { kind: "ready", requestId, initMs: performance.now() - started, networkIsolation };
      self.postMessage(reply);
      return;
    }
    if (!py) throw new Error("sandbox is not initialized");
    py.globals.set("_args", [request.code, request.files, request.collect]);
    const result = await py.runPythonAsync("arena_exec(*_args)");
    if (typeof result !== "string") throw new Error("sandbox returned a non-string result");
    const reply: SandboxReply = { kind: "result", requestId, result };
    self.postMessage(reply);
  } catch (error) {
    const reply: SandboxReply = { kind: "error", requestId,
      error: error instanceof Error ? error.message : String(error) };
    self.postMessage(reply);
  }
};

async function networkSelfCheck(): Promise<"isolated" | "not network-isolated"> {
  let blocked = false;
  try { await fetch(new URL("__arena_sandbox_canary__", self.location.href)); }
  catch { blocked = true; }
  return blocked && self.location.origin === "null" ? "isolated" : "not network-isolated";
}
