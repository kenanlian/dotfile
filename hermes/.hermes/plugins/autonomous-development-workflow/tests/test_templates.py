"""Allowlisted workflow templates: exact ids, no feature switches."""

from __future__ import annotations

import unittest

from plugin_imports import import_plugin

_protocol = import_plugin("controller.protocol")
_types = import_plugin("controller.types")

parse_manifest = _protocol.parse_manifest
WORKFLOW_SCHEMA = _types.WORKFLOW_SCHEMA
WORKFLOW_TEMPLATE_ID = _types.WORKFLOW_TEMPLATE_ID
WorkflowProtocolError = _types.WorkflowProtocolError
WorkflowStatus = _types.WorkflowStatus


def _manifest(**overrides):
    data = {
        "schema": WORKFLOW_SCHEMA,
        "templateId": WORKFLOW_TEMPLATE_ID,
        "board": "project-board",
        "taskId": "t_abc",
        "repoRoot": "/abs/repo",
        "workflowStatus": "queued",
        "revision": 1,
        "baseline": {"branch": "main", "head": "a" * 40},
        "candidateFingerprint": None,
        "approvedPlan": None,
    }
    data.update(overrides)
    return data


class TemplateRegistryTests(unittest.TestCase):
    def test_registry_accepts_only_the_two_allowlisted_templates(self) -> None:
        templates = import_plugin("controller.templates")
        self.assertEqual(
            frozenset(templates.TEMPLATES),
            frozenset({templates.FULL_TEMPLATE_ID, templates.DIRECT_TEMPLATE_ID}),
        )
        self.assertEqual(templates.FULL_TEMPLATE_ID, "autonomous-development.v1")
        self.assertEqual(templates.DIRECT_TEMPLATE_ID, "direct-implementation.v1")
        self.assertEqual(templates.FULL_TEMPLATE_ID, WORKFLOW_TEMPLATE_ID)
        full = templates.get_template("autonomous-development.v1")
        direct = templates.get_template("direct-implementation.v1")
        self.assertEqual(full.flow, "full")
        self.assertEqual(direct.flow, "direct")
        self.assertEqual(full.initial_stage, "plan")
        self.assertEqual(direct.initial_stage, "direct_implement")
        self.assertEqual(full.implement_stage, "implement")
        self.assertEqual(direct.implement_stage, "direct_implement")
        self.assertEqual(full.verification_source, "plan")
        self.assertEqual(direct.verification_source, "intake")
        self.assertTrue(full.uses_review_lane)
        self.assertTrue(full.uses_product_acceptance)
        self.assertFalse(direct.uses_review_lane)
        self.assertFalse(direct.uses_product_acceptance)
        self.assertEqual(set(templates.FLOW_TO_TEMPLATE), {"full", "direct"})
        with self.assertRaises(WorkflowProtocolError):
            templates.get_template("other.v1")
        with self.assertRaises(WorkflowProtocolError):
            templates.template_for_flow("review")

    def test_existing_full_manifests_continue_to_parse(self) -> None:
        parsed = parse_manifest(_manifest())
        self.assertEqual(parsed.template_id, "autonomous-development.v1")
        self.assertEqual(parsed.status, WorkflowStatus.QUEUED)

    def test_direct_manifest_parses_and_unknown_template_fails_closed(self) -> None:
        parsed = parse_manifest(_manifest(templateId="direct-implementation.v1"))
        self.assertEqual(parsed.template_id, "direct-implementation.v1")
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(templateId="other.v1"))
        with self.assertRaises(WorkflowProtocolError):
            parse_manifest(_manifest(templateId="autonomous-development.v2"))

    def test_each_template_owns_statuses_stages_and_transitions(self) -> None:
        templates = import_plugin("controller.templates")
        full = templates.get_template("autonomous-development.v1")
        direct = templates.get_template("direct-implementation.v1")
        self.assertEqual(
            full.allowed_statuses,
            frozenset(WorkflowStatus),
        )
        self.assertEqual(
            direct.allowed_statuses,
            frozenset(
                {
                    WorkflowStatus.QUEUED,
                    WorkflowStatus.IMPLEMENTING,
                    WorkflowStatus.VERIFYING,
                    WorkflowStatus.IMPLEMENT_REWORK,
                    WorkflowStatus.BLOCKED,
                    WorkflowStatus.COMPLETED,
                }
            ),
        )
        self.assertEqual(
            full.allowed_stages,
            frozenset({"plan", "plan_review", "implement", "execute_review"}),
        )
        self.assertEqual(direct.allowed_stages, frozenset({"direct_implement"}))
        self.assertNotIn(WorkflowStatus.IMPLEMENTING, full.allowed_transitions[WorkflowStatus.QUEUED])
        self.assertNotIn(WorkflowStatus.COMPLETED, full.allowed_transitions[WorkflowStatus.VERIFYING])
        self.assertEqual(
            direct.allowed_transitions[WorkflowStatus.QUEUED],
            frozenset({WorkflowStatus.IMPLEMENTING}),
        )
        self.assertEqual(
            full.allowed_transitions[WorkflowStatus.IMPLEMENTING],
            frozenset({WorkflowStatus.VERIFYING}),
        )
        self.assertEqual(
            direct.allowed_transitions[WorkflowStatus.IMPLEMENTING],
            frozenset({WorkflowStatus.VERIFYING, WorkflowStatus.BLOCKED}),
        )

    def test_direct_manifest_rejects_full_only_statuses(self) -> None:
        for status in (
            "planning",
            "plan_reviewing",
            "plan_rework",
            "review_requested",
            "code_reviewing",
            "product_acceptance",
        ):
            with self.subTest(status=status):
                with self.assertRaises(WorkflowProtocolError):
                    parse_manifest(
                        _manifest(templateId="direct-implementation.v1", workflowStatus=status)
                    )


if __name__ == "__main__":
    unittest.main()
