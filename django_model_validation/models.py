from typing import Iterator, Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from django_model_validation.utils import collect_validation_errors
from django_model_validation.validators import ModelValidator


def validator(*, auto: bool = True):
    def decorator(method):
        return ModelValidator(method, auto)

    return decorator


class ModelBaseWithValidators(ModelBase):

    def __new__(cls, name, bases, attrs, **kwargs):
        new_class = super().__new__(cls, name, bases, attrs, **kwargs)

        new_class._model_validators = []

        for attribute_value in attrs.values():
            if isinstance(attribute_value, ModelValidator):
                new_class._register_validator(attribute_value)

        return new_class


class ModelValidationMixin(metaclass=ModelBaseWithValidators):

    @classmethod
    def _register_validator(cls, model_validator: ModelValidator) -> None:
        cls._model_validators.append(model_validator)

    def get_custom_validator_errors(self, *, use_all: bool = False) -> Iterator[ValidationError]:
        for model_validator in self._model_validators:
            if use_all is True or model_validator.auto:
                try:
                    model_validator.get_instance_validator(self).validate()
                except ValidationError as err:
                    yield err

    def run_custom_validators(self, *, use_all: bool = False) -> None:
        errors = list(self.get_custom_validator_errors(use_all=use_all))
        if errors:
            raise ValidationError(errors)

    def check_custom_validators(self, *, use_all: bool = False) -> bool:
        for model_validator in self._model_validators:
            if use_all is True or model_validator.auto:
                if not model_validator.get_instance_validator(self).is_valid():
                    return False

        return True

    def get_custom_validator_results(self, *, use_all: bool = False) -> dict[str, bool]:
        return {
            model_validator.name: model_validator.get_instance_validator(self).is_valid()
            for model_validator in self._model_validators
            if use_all is True or model_validator.auto
        }

    def is_valid(self, *args, use_custom_validators: Optional[bool] = None, **kwargs) -> bool:
        try:
            super().full_clean(*args, **kwargs)
        except ValidationError:
            return False

        return use_custom_validators is False or self.check_custom_validators(
            use_all=use_custom_validators is True,
        )

    @collect_validation_errors
    def full_clean(self, *args, use_custom_validators: Optional[bool] = None, **kwargs):
        try:
            super().full_clean(*args, **kwargs)
        except ValidationError as err:
            yield err

        if use_custom_validators is not False:
            yield from self.get_custom_validator_errors(use_all=use_custom_validators is True)
