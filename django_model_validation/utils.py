from typing import Callable, Iterable

from django.core.exceptions import ValidationError


def collect_validation_errors(old_func: Callable[..., Iterable[ValidationError]]) -> Callable[..., None]:
    """
    Decorator to collect validation errors and raise a single ValidationError if any are encountered.

    This decorator simplifies functions that check multiple conditions and construct a ValidationError containing
    error messages for those that have failed.

    Instead of constructing the ValidationError, the decorated function can simply `yield` errors where errors are
    either `ValidationErrors`, strings containing the error message, a dictionary that maps field names to lists of
    `ValidationErrors` or string error messages, or even a list containing any of the previous.
    """

    def new_func(*args, **kwargs) -> None:
        errors = {}
        for error in old_func(*args, **kwargs):
            ValidationError(error).update_error_dict(errors)
        if errors:
            raise ValidationError(errors)

    new_func.__name__ = old_func.__name__

    return new_func
