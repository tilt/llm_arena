import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";
let py;
self.onmessage = async ({ data }) => {
  try {
    if (data.cmd === "init") {
      const t = performance.now();
      py = await loadPyodide();
      await py.loadPackage(["micropip", "pydantic", "pyyaml", "numpy"]);
      const micropip = py.pyimport("micropip");
      await micropip.install(new URL("../dist/llm_arena-0.1.0-py3-none-any.whl", location.href).href, { deps: false });
      await micropip.install(["rank-bm25"]);
      self.postMessage({ ok: true, seconds: ((performance.now() - t) / 1000).toFixed(1) });
    } else if (data.cmd === "run") {
      const out = await py.runPythonAsync(`
import json
from llm_arena.core.trace import Trace
from llm_arena.eval.base import EvalContext
from llm_arena.llm.testing import ScriptedLLM, tool_call
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RunContext, get_scenario
results = {}
async def run(name, task_id, clients):
    scenario = get_scenario(name)
    task = next(t for t in scenario.load_tasks() if t.id == task_id)
    trace = Trace()
    ctx = RunContext(trace=trace, params=scenario.params())
    output = await scenario.run(task, RoleModels(clients, trace), ctx)
    scores = [s for e in scenario.evaluators(ctx.params) for s in await e.evaluate(EvalContext(task, output, trace))]
    results[f"{name}/{task_id}"] = {s.name: s.passed for s in scores if s.name in scenario.pass_criteria}
await run("email_assistant", "forward_invoice", {"agent": ScriptedLLM([
    tool_call("search_emails", query="invoice"), tool_call("forward_email", email_id=7, to=["accounts@quillon.test"]), "Done."])})
await run("reflection_sql", "total_refunds", {"generator": ScriptedLLM(["SELECT ROUND(-SUM(amount_cents) / 100.0, 2) FROM ledger WHERE entry_type = 'refund'"]),
                                              "critic": ScriptedLLM(['{"verdict": "accept"}'])})
json.dumps(results)
`);
      self.postMessage(JSON.parse(out));
    }
  } catch (err) {
    self.postMessage({ error: String(err).slice(0, 500) });
  }
};
