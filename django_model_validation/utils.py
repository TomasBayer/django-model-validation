from typing import Callable, Iterable

from django.core.exceptions import ValidationError


def collect_validation_errors(old_func: Callable[..., Iterable[ValidationError]]) -> Callable[..., None]:
    def new_func(*args, **kwargs) -> None:
        errors = {}
        for error in old_func(*args, **kwargs):
            ValidationError(error).update_error_dict(errors)
        if errors:
            raise ValidationError(errors)

    new_func.__name__ = old_func.__name__

    return new_func
