from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
ACTION = re.compile(r"^\s*-?\s*uses:\s*[^\s@]+@([0-9a-f]{40})\s+#\s+v\d", re.MULTILINE)
ANY_ACTION = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)


def test_every_github_action_is_immutably_pinned_with_a_release_comment() -> None:
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = workflow.read_text()
        uses = ANY_ACTION.findall(text)
        assert uses, workflow
        assert len(ACTION.findall(text)) == len(uses), f"floating or undocumented action in {workflow}: {uses}"


def test_dependabot_covers_actions_web_and_python_weekly() -> None:
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    updates = {(item["package-ecosystem"], item["directory"]): item for item in config["updates"]}
    assert set(updates) == {("github-actions", "/"), ("npm", "/web"), ("pip", "/")}
    assert all(item["schedule"]["interval"] == "weekly" for item in updates.values())


def test_shared_pages_origin_keeps_browser_keys_session_only() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text()
    assert "ARENA_BASE: /llm_arena/" in workflow
    # tilt.github.io also hosts other projects, so path-based credential trust would not isolate the arena.
    assert "VITE_CREDENTIAL_ORIGIN" not in workflow
