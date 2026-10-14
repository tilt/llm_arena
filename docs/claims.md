# Publishing a claim and getting it on the board

A **claim** says "this model setup passes scenario X at p% for $c per task". You publish it as a public gist, and
anyone can re-run it with their own keys and post a reproduction under it. The
[claims board](https://tilt.github.io/llm_arena/#/board) lists submitted claims and ranks the ones other people have
reproduced. This guide goes from a finished run to a ranked row. It works the same on the public site and in the local
app (`make ui`), except for where the GitHub token goes (step 2).

## 1. Run a scenario

Run any scenario from **Scenarios**, with your own API keys. A claim is judged by the low end of its 95% interval, so
a run on 3 tasks (an interval like [6–79]) ranks far below the same score on 30. When the run can't become a claim,
for example because it uses a live-only parameter or an unpinned judge, its page says why.

## 2. Share it as a claim

On the finished run's page, choose **Share as claim**. If you run self-hosted models, give each one a "compare as" name
first (for example `qwen3-14b`). Others match your model by that name, and your endpoint's name and address are never
shared.

Sharing creates a public gist under your GitHub account with one file, `claim.json`. It holds the setup, which tasks
ran, and the score and cost; your API keys are never in it. This needs a GitHub token with the Gists permission:

- **On the public site:** paste a fine-grained token when asked. Create it at
  [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) with only
  **Account permissions → Gists: Read and write**, and give it an expiry. It can read, edit and delete all your gists, so
  the page keeps it in the tab's memory only; it's gone when you reload.
- **In the local app:** set `GITHUB_TOKEN` in `.env`, or add it under API keys as "GitHub (claims)". If you use the
  GitHub CLI, `GITHUB_TOKEN=$(gh auth token) make ui` works too, without writing the token anywhere.

The result is a claim link like `…#/claim/gist/<id>@<revision>`. The link pins that revision: if you edit the gist
later, the link still shows what you shared, and the page says it was edited.

Without a token you can download `claim.json` and create the gist yourself at gist.github.com, or share a link that
carries the claim itself. That link has no reproduction thread and can't go on the board.

## 3. Submit it to the board

Choose **Submit to board**, on the run page right after sharing or on the claim page. GitHub opens an issue with the
gist and revision filled in. Sign in as the account that owns the gist and press **Create**. Within minutes the board
answers in that issue and closes it:

| Answer in the issue | Label | What it means | What to do |
| --- | --- | --- | --- |
| "Added to the claims board" | `board-accepted` | Listed. It shows on the board a few minutes later, once the site is rebuilt. | Nothing. |
| "Not added: …" | `board-rejected` | The reason follows, for example: only the gist's owner can submit it; the claim isn't valid or was made on another scenario version; it's already on the board or was delisted; the daily limit. | Fix it and submit again. |
| "The board couldn't read the claim this time" | `board-retry` | GitHub had trouble. The issue stays open. | Nothing: the next run (at most 6 hours later) tries again. |
| "The board kept failing to read this claim" | `board-internal-error` | Three tries failed; the maintainer is notified. | Submit again later. It doesn't count toward your limit. |

Each person can submit 5 claims a day, counting accepted and rejected ones. A board holds at most 200 claims.

## 4. On the board

A new claim waits under **Waiting for a first reproduction** until someone other than you reproduces it; your own
runs never count. Then it's ranked:

- **Pass rate** is the share of tasks passed, with its 95% interval. Once others reproduce a claim, their numbers
  replace the claimed ones.
- Setups are **ranked by the low end of the interval**, then by how many steps worked. A high score on a few tasks can
  rank below a slightly lower one on many.
- **Confidence** reads claimed (only the author's run), reproduced (1 or 2 other people) or verified (3 or more), with
  the people's names.

The board rebuilds every 6 hours (at 00:17, 06:17, 12:17 and 18:17 UTC) and whenever someone submits a claim. New
reproductions show at the next rebuild; the board's footer says when that is.

## 5. Getting reproduced

Share the claim link, or let people find it on the board. A reproducer opens it, chooses **Beat this**, runs the claimed
setup with their own keys next to a copy that swaps one model, and chooses **Post reproduction**. That posts a comment
under your gist, which needs their own GitHub token.

The board keeps a witness ledger of every reproduction it has seen. If a recorded comment is later deleted or edited,
it still counts, and the row says so.

## 6. Changing or removing a claim

- **Editing the gist** doesn't change the board, which keeps reading the revision you submitted. To list a changed
  claim, submit its new revision. It's a separate claim, and the old one stays listed.
- **Deleting the gist** keeps the row, marked "gist deleted by its author", without a claim link.
- **When a scenario gets a new version**, claims made on the old one move under "Older scenario versions".
- **Delisting** is done by the maintainer, for example for spam. To ask for it, open an issue.

What the board can't catch, also stated on its page: reproductions are self-reported (one person with several
accounts can inflate a claim), a reproduction deleted before the board saw it, and comments beyond the first 300.
Maintainer setup: [board.md](board.md). Design: [designs/claims-board.md](designs/claims-board.md).
