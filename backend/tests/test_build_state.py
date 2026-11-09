import pytest

from app.models.enums import BuildStatus
from app.services.build_state import ensure_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (BuildStatus.QUEUED, BuildStatus.PARSING),
        (BuildStatus.PARSING, BuildStatus.PREVIEW_READY),
        (BuildStatus.PREVIEW_READY, BuildStatus.INDEXING),
        (BuildStatus.INDEXING, BuildStatus.READY),
        (BuildStatus.READY, BuildStatus.REPLACING),
        (BuildStatus.FAILED, BuildStatus.QUEUED),
    ],
)
def test_valid_build_transitions(current: BuildStatus, target: BuildStatus) -> None:
    ensure_transition(current, target)


def test_invalid_build_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match="queued -> ready"):
        ensure_transition(BuildStatus.QUEUED, BuildStatus.READY)
