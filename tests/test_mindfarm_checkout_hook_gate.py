"""Reproduction test for the mindfarm fork's hooks.py patch.

Root cause 4 (PD44 in the consuming repo, prj-mindfarm): the post-commit
hook template has always carried the GRAPHIFY_SKIP_HOOK escape hatch, but
the post-checkout template never did -- confirmed live and reproducible: a
plain `git checkout` that triggers a branch switch, with the env var set to
skip, had no way to opt out of the background rebuild post-checkout
launches. Upstream template omission, not specific to any one consuming
project -- every project running `graphify hook install` inherited it.
"""
from __future__ import annotations

from graphify.hooks import _HOOK_SCRIPT, _CHECKOUT_SCRIPT


def test_post_commit_template_has_the_skip_gate():
    # Unchanged baseline behavior -- post-commit has always had this.
    assert 'GRAPHIFY_SKIP_HOOK' in _HOOK_SCRIPT


def test_post_checkout_template_now_has_the_skip_gate():
    assert 'GRAPHIFY_SKIP_HOOK' in _CHECKOUT_SCRIPT, (
        "post-checkout template is missing the GRAPHIFY_SKIP_HOOK escape hatch "
        "that post-commit has always had -- see PD44 in the consuming repo's "
        "decision log for the confirmed-live incident this causes"
    )


def test_post_checkout_gate_placed_before_the_background_rebuild_launch():
    """Not just present anywhere in the template -- it must actually gate the
    rebuild, i.e. appear before the detached-launch call, not after."""
    gate_pos = _CHECKOUT_SCRIPT.find('GRAPHIFY_SKIP_HOOK')
    launch_marker_pos = _CHECKOUT_SCRIPT.find('Branch switched - launching background rebuild')
    assert gate_pos != -1 and launch_marker_pos != -1
    assert gate_pos < launch_marker_pos, (
        "GRAPHIFY_SKIP_HOOK gate must appear before the rebuild launch, or it "
        "can't actually skip it"
    )
