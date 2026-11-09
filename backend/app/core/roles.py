"""Experience-mode roles used before real authentication is introduced."""

from enum import StrEnum


class ExperienceRole(StrEnum):
    """UI experience roles.

    These roles reduce accidental operations in the login-free first release;
    they are explicitly not an authentication or tenant-isolation boundary.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"


ROLE_ALIASES: dict[str, ExperienceRole] = {
    "admin": ExperienceRole.ADMIN,
    "administrator": ExperienceRole.ADMIN,
    "manager": ExperienceRole.MANAGER,
    "knowledge_manager": ExperienceRole.MANAGER,
    "knowledge-manager": ExperienceRole.MANAGER,
    "user": ExperienceRole.USER,
}


def parse_experience_role(value: str | None) -> ExperienceRole:
    """Normalize a role header, defaulting absent/blank values to ``user``."""

    if value is None or not value.strip():
        return ExperienceRole.USER
    normalized = value.strip().lower()
    try:
        return ROLE_ALIASES[normalized]
    except KeyError as exc:
        allowed = ", ".join(role.value for role in ExperienceRole)
        raise ValueError(f"unsupported experience role; expected one of: {allowed}") from exc
