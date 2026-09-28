class CoachError(Exception):
    """Base exception for Coach operations."""
    pass


class CoachGoalNotFoundError(CoachError):
    """Raised when a goal is not found."""
    pass


class CoachFocusNotFoundError(CoachError):
    """Raised when a focus is not found."""
    pass


class CoachReflectionNotFoundError(CoachError):
    """Raised when a reflection is not found."""
    pass


class CoachStateValidationError(CoachError):
    """Raised when a state or logic precondition is violated."""
    pass


class CoachDuplicateReflectionError(CoachError):
    """Raised when a reflection for the same focus and ISO week already exists."""
    pass
