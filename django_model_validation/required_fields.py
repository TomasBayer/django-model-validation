from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional, Tuple, Type, Union

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Field, FileField, ManyToManyField

from django_model_validation.utils import collect_validation_errors


@dataclass
class RequiredFieldTester:
    field: Field
    field_tester: Callable[[Field, models.Model], bool]

    def test(self, obj) -> bool:
        return self.field_tester(self.field, getattr(obj, self.field.name))


class RequiredFieldsValidator:

    def __init__(
            self,
            model_type: Type[models.Model],
            required_fields: Iterable[Union[str, tuple[str, Callable[[Any], bool]]]],
    ):
        self.model_type: Type[models.Model] = model_type
        self.required_fields: list[RequiredFieldTester] = [self._parse_entry(entry) for entry in required_fields]

    def _parse_entry(
            self,
            entry: Union[str, Tuple[str, Callable[[Any], bool]]],
    ) -> RequiredFieldTester:
        if isinstance(entry, tuple):
            field_name, field_tester = entry
        else:
            field_name = entry

            if isinstance(field, FileField):
                def field_tester(field, value):
                    return bool(value)
            elif isinstance(field, ManyToManyField):
                def field_tester(field, value):
                    return value.exists()
            else:
                def field_tester(field, value):
                    return value not in field.empty_values

        return RequiredFieldTester(self.model_type._meta.get_field(field_name), field_tester)

    def get_missing_fields(self, obj: models.Model) -> Iterator[Field]:
        for field_tester in self.required_fields:
            if not field_tester.test(obj):
                yield field_tester.field

    @collect_validation_errors
    def validate(
            self,
            obj: models.Model,
            *,
            raise_single_error: bool = False,
            error_message: Optional[str] = None,
    ) -> Iterator[ValidationError]:
        if error_message is not None:
            raise_single_error = True

        if raise_single_error:
            missing_fields = [field.verbose_name for field in self.get_missing_fields(obj)]

            if missing_fields:
                if len(missing_fields) == 1:
                    missing_fields_string = missing_fields[0]
                else:
                    missing_fields_string = f"{', '.join(missing_fields[:-1])} and {missing_fields[-1]}"

                yield ValidationError(
                    f"Some fields are missing: {missing_fields_string}"
                    if error_message is None else error_message,
                )

        else:
            for missing_field in self.get_missing_fields(obj):
                yield ValidationError({missing_field.name: missing_field.error_messages['blank']}, code='blank')


def ensure_values_exist(
        obj: models.Model,
        *required_fields: Union[str, tuple[str, Callable[[Any], bool]]],
        raise_single_error: bool = False,
        error_message: Optional[str] = None,
) -> None:
    RequiredFieldsValidator(obj.__class__, required_fields).validate(
        obj,
        raise_single_error=raise_single_error,
        error_message=error_message,
    )
