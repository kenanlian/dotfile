"""TDD for intent-discussion requirement rendering and persistence."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CREATED_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
FRONTMATTER_KEYS = ("schema", "slug", "title", "status", "created")
SECTION_HEADINGS = (
    "## 目标",
    "## 背景与现状",
    "## 行为规格",
    "## 已决决策",
    "## 非目标",
    "## 约束",
    "## 自动验收",
    "## 人工验收",
    "## 开放问题",
)


def _load_requirement():
    spec = importlib.util.spec_from_file_location(
        "intent_discussion_requirement",
        PLUGIN_ROOT / "requirement.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_requirement = _load_requirement()
write_requirement = _requirement.write_requirement
RequirementError = _requirement.RequirementError


def _valid_kwargs(repo: str, **overrides):
    payload = {
        "repo": repo,
        "slug": "card-filter",
        "title": "卡片筛选",
        "goal": "按标签筛选卡片",
        "context": "当前工作区无法按标签过滤。",
        "behaviors": ["选择标签后列表只显示匹配卡片"],
        "decisions": [{"decision": "使用并集", "rationale": "用户期望宽松匹配"}],
        "non_goals": ["不改存储格式"],
        "constraints": ["保持现有快捷键"],
        "auto_acceptance": ["存在一条命令能判定筛选结果"],
        "manual_acceptance": [
            {
                "scenario": "选中标签A后查看列表",
                "expected": "仅显示带标签A的卡片",
                "evidence": ".dev/acceptance/filter.png",
            }
        ],
        "open_questions": [],
        "overwrite": False,
    }
    payload.update(overrides)
    return payload


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise AssertionError("missing opening frontmatter fence")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AssertionError("missing closing frontmatter fence")
    fields: dict[str, str] = {}
    keys: list[str] = []
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(": ")
        if not sep:
            raise AssertionError(f"malformed frontmatter line: {line!r}")
        keys.append(key)
        fields[key] = value
    if tuple(keys) != FRONTMATTER_KEYS:
        raise AssertionError(f"frontmatter key order {keys!r} != {FRONTMATTER_KEYS!r}")
    return fields


class WriteRequirementTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_valid_input_persists_file_frontmatter_and_sha256(self) -> None:
        result = write_requirement(**_valid_kwargs(str(self.repo)))
        dest = self.repo / ".dev" / "requirements" / "card-filter.md"
        self.assertTrue(dest.is_file())
        raw = dest.read_bytes()
        text = raw.decode("utf-8")
        fields = _parse_frontmatter(text)
        self.assertEqual(fields["schema"], "intent-discussion.requirement.v1")
        self.assertEqual(fields["slug"], "card-filter")
        self.assertEqual(fields["title"], "卡片筛选")
        self.assertEqual(fields["status"], "ready")
        self.assertRegex(fields["created"], CREATED_RE)
        self.assertEqual(result["path"], str(dest))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["bytes"], dest.stat().st_size)
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["bytes"], len(raw))
        positions = [text.index(heading) for heading in SECTION_HEADINGS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("# 卡片筛选", text)
        self.assertIn("- **使用并集** — 用户期望宽松匹配", text)

    def test_open_questions_nonempty_is_draft_empty_is_ready(self) -> None:
        ready = write_requirement(**_valid_kwargs(str(self.repo)))
        ready_path = Path(ready["path"])
        ready_text = ready_path.read_text(encoding="utf-8")
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(_parse_frontmatter(ready_text)["status"], "ready")
        self.assertIn("\n无\n", ready_text[ready_text.index("## 开放问题") :])

        draft_repo = Path(tempfile.mkdtemp(dir=self.repo))
        draft = write_requirement(
            **_valid_kwargs(
                str(draft_repo),
                open_questions=["筛选是并集还是交集？"],
            )
        )
        draft_text = Path(draft["path"]).read_text(encoding="utf-8")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(_parse_frontmatter(draft_text)["status"], "draft")
        self.assertIn("- 筛选是并集还是交集？", draft_text)

    def test_invalid_slug_uppercase_raises(self) -> None:
        with self.assertRaises(RequirementError):
            write_requirement(**_valid_kwargs(str(self.repo), slug="Card-filter"))

    def test_invalid_slug_underscore_raises(self) -> None:
        with self.assertRaises(RequirementError):
            write_requirement(**_valid_kwargs(str(self.repo), slug="card_filter"))

    def test_invalid_slug_empty_raises(self) -> None:
        with self.assertRaises(RequirementError):
            write_requirement(**_valid_kwargs(str(self.repo), slug=""))

    def test_existing_without_overwrite_raises(self) -> None:
        write_requirement(**_valid_kwargs(str(self.repo)))
        with self.assertRaises(RequirementError):
            write_requirement(**_valid_kwargs(str(self.repo), goal="第二次写入"))

    def test_existing_with_overwrite_succeeds(self) -> None:
        first = write_requirement(**_valid_kwargs(str(self.repo)))
        dest = Path(first["path"])
        original = dest.read_text(encoding="utf-8")
        second = write_requirement(
            **_valid_kwargs(str(self.repo), goal="覆盖后的目标", overwrite=True)
        )
        updated = dest.read_text(encoding="utf-8")
        self.assertEqual(second["path"], str(dest))
        self.assertIn("覆盖后的目标", updated)
        self.assertNotEqual(original, updated)
        self.assertEqual(
            second["sha256"], hashlib.sha256(dest.read_bytes()).hexdigest()
        )

    def test_zero_acceptance_raises(self) -> None:
        with self.assertRaises(RequirementError):
            write_requirement(
                **_valid_kwargs(
                    str(self.repo),
                    auto_acceptance=[],
                    manual_acceptance=[],
                )
            )

    def test_relative_repo_raises(self) -> None:
        with self.assertRaises(RequirementError):
            write_requirement(**_valid_kwargs("relative/repo"))

    def test_missing_repo_raises(self) -> None:
        missing = self.repo / "does-not-exist"
        with self.assertRaises(RequirementError):
            write_requirement(**_valid_kwargs(str(missing)))


if __name__ == "__main__":
    unittest.main()
