"""Single source of truth for import/indexing state transitions."""

from app.models.enums import BuildStatus

_ALLOWED = {
    BuildStatus.QUEUED: {BuildStatus.PARSING, BuildStatus.CANCELLED, BuildStatus.FAILED},
    BuildStatus.PARSING: {BuildStatus.PREVIEW_READY, BuildStatus.CANCELLED, BuildStatus.FAILED},
    BuildStatus.PREVIEW_READY: {
        BuildStatus.INDEXING,
        BuildStatus.REPLACING,
        BuildStatus.CANCELLED,
        BuildStatus.FAILED,
    },
    BuildStatus.INDEXING: {BuildStatus.READY, BuildStatus.CANCELLED, BuildStatus.FAILED},
    BuildStatus.REPLACING: {
        BuildStatus.PARSING,
        BuildStatus.INDEXING,
        BuildStatus.READY,
        BuildStatus.CANCELLED,
        BuildStatus.FAILED,
    },
    BuildStatus.FAILED: {BuildStatus.QUEUED},
    BuildStatus.CANCELLED: {BuildStatus.QUEUED},
    BuildStatus.READY: {BuildStatus.REPLACING},
}


def ensure_transition(current: BuildStatus, target: BuildStatus) -> None:
    if target not in _ALLOWED.get(current, set()):
        raise ValueError(f"invalid build transition: {current.value} -> {target.value}")
