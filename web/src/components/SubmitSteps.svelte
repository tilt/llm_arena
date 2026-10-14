<script lang="ts">
  // What happens after "Submit to board" (docs/claims.md), shown wherever the button is.
  import { GUIDE } from "../lib/board";
</script>

<ol class="submit-steps">
  <li>GitHub opens a prefilled issue. Sign in as the account that owns the claim's gist, and press <b>Create</b>.</li>
  <li>Within minutes the board answers in that issue: added, or not added with the reason.</li>
  <li>The claim then shows on the <a href="#/board">board</a> under "Waiting for a first reproduction".</li>
  <li>It's ranked once someone else reproduces it; your own runs don't count. New reproductions show at the next
    update, every 6 hours.</li>
</ol>
<span>At most 5 submissions per person per day. <a href={GUIDE} target="_blank" rel="noopener">The full guide</a></span>

<style>
  .submit-steps { margin: 0 0 4px; padding-left: 18px; }
  .submit-steps li { margin: 2px 0; }
</style>
