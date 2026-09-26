/// <reference lib="webworker" />
// Runs model-written Python in its own Pyodide, away from the engine. The engine terminates this
// worker on timeout (and starts a fresh one), which is the browser's equivalent of killing a process.
import { loadPyodide, type Pyodide } from "./pyodide";

let py: Pyodide | null = null;

const EXEC = String.raw`
import base64, contextlib, glob, io, json, os, runpy, sys, tempfile, traceback

def arena_exec(code, files_json, collect_json):
    workdir = tempfile.mkdtemp(prefix="arena-")
    for name, b64 in json.loads(files_json).items():
        path = os.path.join(workdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(b64))
    with open(os.path.join(workdir, "main.py"), "w") as handle:
        handle.write(code)
    # Modules imported by a previous run (e.g. the shop's api.py) must not leak into this one.
    for name, module in list(sys.modules.items()):
        if (getattr(module, "__file__", "") or "").startswith(tempfile.gettempdir()):
            del sys.modules[name]
    previous = os.getcwd()
    os.chdir(workdir)
    sys.path.insert(0, workdir)
    out, err, returncode = io.StringIO(), io.StringIO(), 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            runpy.run_path("main.py", run_name="__main__")
        except SystemExit as exc:
            returncode = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except BaseException:
            traceback.print_exc()
            returncode = 1
    if "matplotlib.pyplot" in sys.modules:
        sys.modules["matplotlib.pyplot"].close("all")
    collected = {}
    for pattern in json.loads(collect_json):
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                with open(path, "rb") as handle:
                    collected[path] = base64.b64encode(handle.read()).decode("ascii")
    os.chdir(previous)
    sys.path.remove(workdir)
    return json.dumps({"stdout": out.getvalue()[-8000:], "stderr": err.getvalue()[-8000:], "returncode": returncode,
                       "timed_out": False, "files": collected})
`;

self.onmessage = async ({ data }: MessageEvent<{ cmd: "init" } | { cmd: "exec"; code: string; files: string; collect: string }>) => {
  if (data.cmd === "init") {
    py = await loadPyodide();
    await py.loadPackage(["matplotlib", "pandas"]);
    await py.runPythonAsync(`import os\nos.environ["MPLBACKEND"] = "Agg"\n${EXEC}`);
    self.postMessage("ready");
    return;
  }
  py!.globals.set("_args", [data.code, data.files, data.collect]);
  const result = await py!.runPythonAsync("arena_exec(*_args)");
  self.postMessage(result);
};
