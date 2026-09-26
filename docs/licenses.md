# Third-party datasets

Datasets are downloaded at runtime from the Hugging Face Hub into `data/cache/hf` (git-ignored) at pinned commits. They
are never redistributed with this repository.

| Benchmark | Dataset | Revision | Licence |
|---|---|---|---|
| gsm8k | `openai/gsm8k` (main/test) | `740312add88f781978c0658806c59bc2815b9866` | MIT |
| mmlu_pro | `TIGER-Lab/MMLU-Pro` (test) | `b189ec765aa7ed75c8acfea42df31fdae71f97be` | MIT |
| humaneval | `openai/openai_humaneval` | `7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544` | MIT |
| mbpp | `google-research-datasets/mbpp` (sanitized/test) | `4bb6404fdc6cacfda99d4ac4205087b89d32030c` | CC-BY-4.0 |
| ifeval | `google/IFEval` | `966cd89545d6b6acfd7638bc708b98261ca58e84` | Apache-2.0 |

The IFEval instruction checkers and the function-calling suite are our own implementations. All scenario data is
original and synthetic.
