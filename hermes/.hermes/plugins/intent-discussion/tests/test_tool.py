"""TDD for intent-discussion tool handler and schema."""

from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PKG = "intent_discussion"

REQUIRED_FIELDS = [
    "repo",
    "slug",
    "title",
    "goal",
    "context",
    "behaviors",
    "decisions",
    "non_goals",
    "constraints",
    "auto_acceptance",
    "manual_acceptance",
    "open_questions",
]


def _ensure_plugin_package() -> None:
    existing = sys.modules.get(PKG)
    if existing is not None and getattr(existing, "__path__", None):
        return
    pkg = types.ModuleType(PKG)
    pkg.__file__ = str(PLUGIN_ROOT / "__init__.py")
    pkg.__path__ = [str(PLUGIN_ROOT)]
    pkg.__package__ = PKG
    sys.modules[PKG] = pkg


_ensure_plugin_package()
schemas = importlib.import_module(f"{PKG}.schemas")
tools = importlib.import_module(f"{PKG}.tools")

REQUIREMENT_WRITE = schemas.REQUIREMENT_WRITE
requirement_write = tools.requirement_write


def _valid_args(repo: str, **overrides) -> dict:
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


def _json_schema(schema: dict) -> dict:
    params = schema.get("parameters")
    if isinstance(params, dict) and (
        params.get("type") == "object" or "properties" in params
    ):
        return params
    return schema


class RequirementWriteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_handler_success_persists_file_and_returns_metadata(self) -> None:
        result = requirement_write(_valid_args(str(self.repo)), ctx=object())
        dest = self.repo / ".dev" / "requirements" / "card-filter.md"
        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result)
        self.assertEqual(result["path"], str(dest))
        self.assertTrue(dest.is_file())
        raw = dest.read_bytes()
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["bytes"], len(raw))

    def test_handler_requirement_error_returns_error_dict(self) -> None:
        result = requirement_write(_valid_args(str(self.repo), slug="Bad_Slug"))
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertIsInstance(result["error"], str)
        self.assertTrue(result["error"])
        self.assertFalse(
            (self.repo / ".dev" / "requirements" / "Bad_Slug.md").exists()
        )

    def test_schema_rejects_unknown_fields(self) -> None:
        schema = _json_schema(REQUIREMENT_WRITE)
        self.assertIs(schema.get("additionalProperties"), False)
        properties = schema.get("properties") or {}
        self.assertNotIn("unknown_field", properties)
        self.assertNotIn("enqueue", properties)
        self.assertEqual(list(schema.get("required") or []), REQUIRED_FIELDS)
        self.assertNotIn("overwrite", schema.get("required") or [])
        description = str(REQUIREMENT_WRITE.get("description") or "")
        self.assertIn("这是持久化 requirement 的唯一方式", description)
        self.assertIn("先完成讨论收敛再调用", description)
        self.assertIn("open_questions 非空时产出为 draft", description)
        self.assertIn("不得 enqueue", description)


if __name__ == "__main__":
    unittest.main()
