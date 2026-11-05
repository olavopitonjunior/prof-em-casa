from pydantic import BaseModel, ConfigDict, StrictInt, model_validator

from app.domain.division.errors import DomainError

MAX_DIVIDEND = 30
MIN_DIVISOR = 2
MAX_DIVISOR = 6


class TaskSpec(BaseModel):
    """Tarefa de divisão exata por partilha dentro dos limites do motor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dividend: StrictInt
    divisor: StrictInt
    unit: str

    @model_validator(mode="after")
    def _check_engine_limits(self) -> "TaskSpec":
        if not 1 <= self.dividend <= MAX_DIVIDEND:
            raise DomainError("UNSUPPORTED_CONTENT", f"dividend must be 1..{MAX_DIVIDEND}")
        if not MIN_DIVISOR <= self.divisor <= MAX_DIVISOR:
            raise DomainError(
                "UNSUPPORTED_CONTENT", f"divisor must be {MIN_DIVISOR}..{MAX_DIVISOR}"
            )
        if self.dividend % self.divisor != 0:
            raise DomainError("UNSUPPORTED_CONTENT", "division must be exact")
        return self
