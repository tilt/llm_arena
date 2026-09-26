import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";
let py;
self.onmessage = async ({ data }) => {
  try {
    if (data.cmd === "init") {
      const t = performance.now();
      py = await loadPyodide();
      await py.loadPackage(["matplotlib"]);
      self.postMessage({ ok: true, seconds: ((performance.now() - t) / 1000).toFixed(1) });
    } else if (data.cmd === "exec") {
      py.FS.writeFile("/home/pyodide/user_code.py", data.code);
      const out = await py.runPythonAsync(`
import os, json, matplotlib
matplotlib.use("Agg")
os.chdir("/home/pyodide")
exec(compile(open("user_code.py").read(), "user_code.py", "exec"), {"__name__": "__main__"})
import matplotlib.pyplot as plt
ax = plt.gcf().axes[0]
json.dumps({"png_bytes": os.path.getsize("chart.png"), "lines": len(ax.get_lines()), "title": ax.get_title()})
`);
      self.postMessage(JSON.parse(out));
    }
  } catch (err) {
    self.postMessage({ error: String(err).slice(0, 500) });
  }
};
