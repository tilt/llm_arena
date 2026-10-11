# Claims board: maintainer setup

The board is built by `.github/workflows/board.yml` and stored on the `board-data` branch. Design and decisions:
[designs/claims-board.md](designs/claims-board.md). One-time setup before the first run:

1. **Create the data branch.** It holds `board/registry.json`, `board/claims/<claim_hash>.json`,
   `board/ledger.jsonl` and `board/board.json`, written only by the board workflow:

   ```sh
   git switch --orphan board-data && git commit --allow-empty -m "board data" && git push origin board-data
   git switch main
   ```

2. **Protect it.** Add a repository ruleset for `board-data` that blocks force pushes and deletion, with no bypass.
   Ordinary pushes from the workflow still work. Builds also refuse evidence that changed since the previous build
   (the registry, removed list and ledger only grow; the ledger is hash-chained; cached claims match their hashes).

3. **Add the read token.** The Actions token can't read gists (GitHub answers 403), so create a fine-grained personal
   access token with **public repositories (read-only)** access and no other permissions, and store it as the
   repository secret `BOARD_READ_TOKEN`. Give it an expiry (for example 90 days) and a reminder to rotate it. When it
   expires, board runs fail with a message naming the token, and submissions stay open until it works again.

4. **Create the label** `claim-submission` (issue forms only apply labels that exist). The board creates its answer
   labels (`board-accepted`, `board-rejected`, `board-retry`, `board-internal-error`) when it first uses them.

## Running it

- Every 6 hours, on each new submission issue, and from the Actions tab (`workflow_dispatch`). A run answers open
  submissions, reads each listed gist (one request plus up to three comment pages), pushes `board-data`, answers the
  issues, then deploys Pages through `pages.yml`, building current `main`.
- A build stops without writing when the token is refused, the hourly request budget runs low, more than 20% of the
  gists can't be read, or any evidence check fails; the published board stays as it was.
- To delist a claim, append `{"claim_hash": ..., "reason": ..., "at": ...}` to `removed` in `board/registry.json` on
  `board-data` (never edit or delete earlier entries). It disappears from the board and is listed as delisted for 30
  days.
- Local check: `uv run arena board run --offline --data <checkout of board-data> --actions /tmp/actions.json`.

What the board can't catch, also stated on the page: reproductions are self-reported (several accounts can inflate a
claim), a reproduction deleted before the first build that saw it, comments beyond the first 300, and direct pushes by
people with write access to `board-data` made in a way that also rewrites `board.json`.
