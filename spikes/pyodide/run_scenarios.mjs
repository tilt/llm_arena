// Phase 0 spike, step 2: run real scenarios inside Pyodide, scripted and via a fetch-based OpenAI transport.
// Usage: OPENAI_API_KEY=... node run_scenarios.mjs dist/llm_arena-0.1.0-py3-none-any.whl
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { loadPyodide } from "pyodide";

const wheel = process.argv[2];
const t0 = performance.now();
const py = await loadPyodide({ stdout: (s) => console.log("[py]", s) });
await py.loadPackage(["micropip", "pydantic", "pyyaml", "numpy"]);
py.FS.writeFile(`/tmp/${basename(wheel)}`, readFileSync(wheel));
const micropip = py.pyimport("micropip");
await micropip.install(`emfs:/tmp/${basename(wheel)}`, { deps: false });
// BM25 is vendored now; no extra packages
console.log(`setup ${((performance.now() - t0) / 1000).toFixed(1)}s`);
py.globals.set("OPENAI_KEY", process.env.OPENAI_API_KEY ?? "");

await py.runPythonAsync(`
import time

from llm_arena.core.trace import Trace
from llm_arena.eval.base import EvalContext
from llm_arena.adapters.browser.pyfetch_transport import PyfetchTransport
from llm_arena.llm.http_client import ProtocolClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.testing import ScriptedLLM, tool_call
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RunContext, get_scenario


async def run(name, task_id, clients, **params):
    scenario = get_scenario(name)
    task = next(t for t in scenario.load_tasks() if t.id == task_id)
    trace = Trace()
    ctx = RunContext(trace=trace, params=scenario.params(params))
    started = time.perf_counter()
    output = await scenario.run(task, RoleModels(clients, trace), ctx)
    scores = [s for e in scenario.evaluators(ctx.params) for s in await e.evaluate(EvalContext(task, output, trace))]
    passed = {s.name: s.passed for s in scores if s.name in scenario.pass_criteria}
    print(f"{name}/{task_id}: {time.perf_counter() - started:.2f}s pass={passed} spans={len(trace.spans)}")

GOOD_SQL = ("\`\`\`sql\\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
            "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\\n\`\`\`")
await run("reflection_sql", "harborview_march_rentals",
          {"generator": ScriptedLLM([GOOD_SQL]), "critic": ScriptedLLM(['{"verdict": "accept"}'])})
await run("email_assistant", "forward_invoice", {"agent": ScriptedLLM([
    tool_call("search_emails", query="invoice"), tool_call("forward_email", email_id=7, to=["accounts@quillon.test"]), "Done."])})
await run("react_multihop", "hq_river_selmworks", {"agent": ScriptedLLM([
    'Action: read_article\\nAction Input: {"title": "Selmworks"}', 'Action: read_article\\nAction Input: {"title": "Durnhollow"}',
    "Final Answer: Ember"])})

if OPENAI_KEY:
    spec = ModelSpec(name="openai:gpt-4.1-nano", provider="openai", model="gpt-4.1-nano")
    try:
        await run("email_assistant", "offsite_question", {"agent": ProtocolClient(spec, PyfetchTransport(), api_key=OPENAI_KEY, browser=True)})
    except Exception as exc:
        print("live OpenAI via fetch:", type(exc).__name__, str(exc)[:200])
`);
console.log(`total ${((performance.now() - t0) / 1000).toFixed(1)}s`);
