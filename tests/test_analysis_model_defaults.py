from src.agent.core import FALLBACK_MODEL_NAME as AGENT_FALLBACK_MODEL
from src.agent.core import MODEL_NAME as AGENT_MODEL
from src.analysis.classifier import DEFAULT_FALLBACK_MODEL, DEFAULT_MAX_TOKENS, DEFAULT_OPENROUTER_MODEL
from src.report.composer import DEFAULT_FALLBACK_MODEL as REPORT_FALLBACK_MODEL
from src.report.composer import DEFAULT_REPORT_MODEL


def test_default_openrouter_models_use_current_provider_ids() -> None:
    """기본값은 OpenRouter에 실제로 등록된 버전 고정 모델이어야 한다."""
    assert DEFAULT_OPENROUTER_MODEL == "deepseek/deepseek-v4-flash-0731"
    assert DEFAULT_FALLBACK_MODEL == "openrouter/free"
    assert AGENT_MODEL == DEFAULT_OPENROUTER_MODEL
    assert AGENT_FALLBACK_MODEL == DEFAULT_FALLBACK_MODEL
    assert DEFAULT_REPORT_MODEL == DEFAULT_OPENROUTER_MODEL
    assert REPORT_FALLBACK_MODEL == DEFAULT_FALLBACK_MODEL
