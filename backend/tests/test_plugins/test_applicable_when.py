import pytest

from lumina.plugins.base import (
    ApplicableWhen,
    PluginContext,
    SelectionTypeRule,
    SelectionWordCountRule,
    evaluate_applicable_when,
)


def test_aw01_rule_none() -> None:
    assert evaluate_applicable_when(None, PluginContext()) is True


def test_aw02_max_closed_interval() -> None:
    rule = ApplicableWhen(selection_word_count=SelectionWordCountRule(max=3))
    assert evaluate_applicable_when(rule, PluginContext(selection_word_count=3)) is True


def test_aw03_max_exceeded() -> None:
    rule = ApplicableWhen(selection_word_count=SelectionWordCountRule(max=3))
    assert evaluate_applicable_when(rule, PluginContext(selection_word_count=4)) is False


def test_aw04_min_not_met() -> None:
    rule = ApplicableWhen(selection_word_count=SelectionWordCountRule(min=1))
    assert evaluate_applicable_when(rule, PluginContext(selection_word_count=0)) is False


def test_aw05_min_max_range() -> None:
    rule = ApplicableWhen(
        selection_word_count=SelectionWordCountRule(min=1, max=3)
    )
    assert evaluate_applicable_when(rule, PluginContext(selection_word_count=2)) is True


def test_aw06_selection_type_mismatch() -> None:
    rule = ApplicableWhen(
        selection_type=SelectionTypeRule.model_validate({"in": ["text"]})
    )
    assert (
        evaluate_applicable_when(rule, PluginContext(selection_type="image"))
        is False
    )


def test_aw07_selection_type_match() -> None:
    rule = ApplicableWhen(
        selection_type=SelectionTypeRule.model_validate({"in": ["text", "image"]})
    )
    assert (
        evaluate_applicable_when(rule, PluginContext(selection_type="image"))
        is True
    )


def test_aw08_both_rules_satisfied() -> None:
    rule = ApplicableWhen(
        selection_word_count=SelectionWordCountRule(max=3),
        selection_type=SelectionTypeRule.model_validate({"in": ["image"]}),
    )
    ctx = PluginContext(selection_word_count=2, selection_type="image")
    assert evaluate_applicable_when(rule, ctx) is True


def test_aw09_type_fails_short_circuit() -> None:
    rule = ApplicableWhen(
        selection_word_count=SelectionWordCountRule(max=3),
        selection_type=SelectionTypeRule.model_validate({"in": ["text"]}),
    )
    ctx = PluginContext(selection_word_count=2, selection_type="image")
    assert evaluate_applicable_when(rule, ctx) is False
