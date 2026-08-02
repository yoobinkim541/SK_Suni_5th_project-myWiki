class AnalysisError(Exception):
    """Base exception for analysis classification errors."""


class MissingApiKeyError(AnalysisError):
    pass


class DocumentNotFoundError(AnalysisError):
    pass


class MarkdownNotFoundError(AnalysisError):
    pass


class OpenRouterTimeoutError(AnalysisError):
    pass


class OpenRouterApiError(AnalysisError):
    pass


class InvalidJsonResponseError(AnalysisError):
    pass


class InvalidCategoryError(AnalysisError):
    pass


class InvalidScoreError(AnalysisError):
    pass


class InsufficientEvidenceError(AnalysisError):
    pass


class DocumentVersionNotFoundError(AnalysisError):
    pass


class DocumentWorkspaceMismatchError(AnalysisError):
    pass


class ClassificationSaveFailedError(AnalysisError):
    pass


class ClassificationLoadFailedError(AnalysisError):
    pass


class InvalidCoreSummaryError(AnalysisError):
    pass


class InvalidKeyPointsError(AnalysisError):
    pass


class InvalidKeyNumbersError(AnalysisError):
    pass


class InvalidSummaryEvidenceError(AnalysisError):
    pass


class InvalidSkHynixImplicationError(AnalysisError):
    pass


class RankingSaveFailedError(AnalysisError):
    pass


class RankingLoadFailedError(AnalysisError):
    pass
