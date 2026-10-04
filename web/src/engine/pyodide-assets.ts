export interface VerifiedAsset {
  file: string;
  sha256: string;
}

export const PYODIDE_VERSION = "314.0.7";
export const PYODIDE_BASE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

export const PYODIDE_CORE: Record<string, VerifiedAsset> = {
  module: { file: "pyodide.mjs", sha256: "6f1d60f7bf529beb300f0f47983c921d3982363640ba20af0e38efdddbc66109" },
  asm: { file: "pyodide.asm.mjs", sha256: "f7cdc8ece80678ceb712f8e65ebe6d3a83203a180c399865f49612a051693635" },
  wasm: { file: "pyodide.asm.wasm", sha256: "cc36e3cab04fdfc9a63ff13eb52eae2b911bf46c025cc7b281f394bd3de1d5e6" },
  stdlib: { file: "python_stdlib.zip", sha256: "fa1957e5777068fc4f7437f96d860ae2fbe9c19732ba06c84e004ec16dd7dd7a" },
  lock: { file: "pyodide-lock.json", sha256: "5dc2fc119108bc148c7457dc86e7675b5c87e1cafd420b9c34c1eaef7b36c010" },
};

export const SANDBOX_PACKAGE_NAMES = ["matplotlib", "pandas"] as const;
export const SANDBOX_PACKAGES: VerifiedAsset[] = [
  { file: "contourpy-1.3.3-cp314-cp314-pyemscripten_2026_0_wasm32.whl", sha256: "0ac15ebf9f820d2d1c3526388aa2818b631cb6c4aae1682efd6b4cc12c1f302c" },
  { file: "cycler-0.12.1-py3-none-any.whl", sha256: "8ee450085f15b47f78b034d60059af6a3649e98fa5dde073363437742cc0b4ea" },
  { file: "fonttools-4.62.1-py3-none-any.whl", sha256: "0d1516e073fd0a8d8e6d9af46417b6a26209a42518024a18f7085e72d2599605" },
  { file: "kiwisolver-1.5.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl", sha256: "47781998156721147c128a3c74547d5703e0e3cc454d8203e629339368308a93" },
  { file: "matplotlib-3.10.8-cp314-cp314-pyemscripten_2026_0_wasm32.whl", sha256: "722857932f8f62eac64f8439af15c94d427f9fb945f9590cd242805c983d2d54" },
  { file: "numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl", sha256: "a292c1f5d7d8a2208cd5e94fc467604c131cabcd2fc14fed6eefde121e7fabdf" },
  { file: "packaging-26.1-py3-none-any.whl", sha256: "565acbbea54da30348b6d68b6a54373e6f777987db9f1db6966b4b3a5060d303" },
  { file: "pandas-3.0.2-cp314-cp314-pyemscripten_2026_0_wasm32.whl", sha256: "45ff57772cc2f366a8582c7d3097cc4e6676342ecd5a3c08184a43462d5a02ae" },
  { file: "pillow-12.2.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl", sha256: "e29838b7a756e4ee0f27a9cfa9a387ee0dfa2e9dd44be2dd595130b9f9d93ac3" },
  { file: "pyparsing-3.3.2-py3-none-any.whl", sha256: "f0dd8225b5f8e945980b400bd465b4b90cb0498a2eede0d9dbea98372f6110c5" },
  { file: "python_dateutil-2.9.0.post0-py2.py3-none-any.whl", sha256: "9b13365edf9c188f570baf9c540bbb3029ada2a2dacb9694b3659941693ee9e5" },
  { file: "pytz-2026.1.post1-py2.py3-none-any.whl", sha256: "b8249d6450146e0b61e6d710dc02ebb35a904796c4c2f97fe87d4ac5872db36a" },
  { file: "six-1.17.0-py2.py3-none-any.whl", sha256: "228c50f73aa7addf2c2ccf2979c256802a59ab69cad8152b31b9443cc8140f42" },
];
