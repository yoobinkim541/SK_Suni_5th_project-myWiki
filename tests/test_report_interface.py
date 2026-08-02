from __future__ import annotations

from inspect import signature
from typing import get_type_hints

from src.report.interface import DailyReportGenerationResult, ReportGenerationConfig, generate_daily_report
from src.report.models import ReportGenerationRequest


def test_generate_daily_report_signature_uses_report_models() -> None:
    hints = get_type_hints(generate_daily_report)
    params = signature(generate_daily_report).parameters

    assert list(params.keys()) == ["request", "supabase", "llm_client", "generated_at", "config"]
    assert hints["request"] is ReportGenerationRequest
    assert hints["return"] is DailyReportGenerationResult


def test_report_generation_config_has_component_configs() -> None:
    config = ReportGenerationConfig()

    assert config.selection.max_candidates is None
    assert config.selection.min_reliability_score == 70
    assert config.selection.min_importance_score == 70
    assert config.wiki.limit_per_group >= 0
    assert config.composer.prompt_version
