from dataclasses import dataclass, field
from types import GeneratorType
from typing import Callable, Optional, Type

from django.core.exceptions import ValidationError
from django.db import models


@dataclass
class ModelInstanceValidator:
    model_validator: 'ModelValidator'
    model_instance: models.Model

    def get_validation_error(self) -> Optional[ValidationError]:
        try:
            result = self.model_validator.method(self.model_instance)

            if isinstance(result, bool):
                if not result:
                    return ValidationError(f"The validator \"{self.model_validator.name}\" failed.")
                else:
                    return None

            if isinstance(result, GeneratorType):
                result = list(result)

            if result:
                return ValidationError(result)
        except ValidationError as err:
            return err

        return None

    def validate(self) -> None:
        validation_error = self.get_validation_error()

        if validation_error is not None:
            raise validation_error

    def is_valid(self) -> bool:
        try:
            self.validate()
            return True
        except ValidationError:
            return False

    def __call__(self) -> None:
        self.validate()


@dataclass
class ModelValidator:
    method: Callable
    auto: bool

    model_type: Type[models.Model] = field(init=False, default=None)

    @property
    def name(self) -> str:
        return self.method.__name__

    def get_instance_validator(self, obj: models.Model) -> ModelInstanceValidator:
        return ModelInstanceValidator(self, obj)

    def __set_name__(self, model_type: models.Model, name: str):
        self.model_type = model_type

    def __get__(self, instance: models.Model, cls=None):
        if instance is None:
            return self
        else:
            return self.get_instance_validator(instance)