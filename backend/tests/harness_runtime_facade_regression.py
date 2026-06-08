"""Harness runtime facade regression tests are split by runtime authority.

The historical catch-all file was too large to diagnose as a single run.  Add
new coverage to the focused modules next to this file instead of rebuilding the
monolith. Shared fixtures and stubs live in
``tests.support.harness_runtime_facade_support``.

Current focused modules:

- harness_context_policy_regression.py
- harness_runtime_projection_regression.py
- harness_single_agent_tool_runtime_regression.py
- harness_task_lifecycle_control_regression.py
- harness_task_executor_control_regression.py
- harness_active_work_control_regression.py
- harness_model_action_protocol_regression.py
- harness_task_artifact_completion_regression.py
"""
