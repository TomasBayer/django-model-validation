from typing import Iterator, Optional, Type

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Manager, Q, QuerySet
from django.db.models.base import ModelBase

from django_model_validation.utils import collect_validation_errors
from django_model_validation.validators import ModelValidator


def validator(
        *,
        auto: bool = True,
        cache: bool = False,
        auto_use_cache: bool = True,
        auto_update_cache: bool = True,
        property_name: Optional[str] = None,
        property_verbose_name: Optional[str] = None,
):
    def decorator(method):
        return ModelValidator(
            method,
            auto,
            cache,
            auto_use_cache,
            auto_update_cache,
            property_name,
            property_verbose_name,
        )

    return decorator


class ModelBaseWithValidators(ModelBase):

    def __new__(cls, name, bases, attrs, **kwargs):
        new_class = super().__new__(cls, name, bases, attrs, **kwargs)

        new_class._model_validators = []

        for attribute_value in attrs.values():
            if isinstance(attribute_value, ModelValidator):
                new_class._register_validator(attribute_value)

        return new_class


class ValidatingModelManager(Manager):

    def __init__(self, *, exclude_valid: bool = False, exclude_invalid: bool = False):
        super().__init__()
        self.exclude_valid = exclude_valid
        self.exclude_invalid = exclude_invalid

    def get_queryset(self):
        qs = super().get_queryset()
        if self.exclude_valid:
            qs = qs.exclude(self.model.get_custom_validity_condition())
        if self.exclude_invalid:
            qs = qs.exclude(~self.model.get_custom_validity_condition())
        return qs

    def __set_name__(self, model_type: Type['ValidatingModel']):
        self.model = model_type


class ValidatingModel(models.Model, metaclass=ModelBaseWithValidators):
    objects = ValidatingModelManager()
    valid_objects = ValidatingModelManager(exclude_valid=True)
    invalid_objects = ValidatingModelManager(exclude_invalid=True)

    @classmethod
    def _register_validator(cls, model_validator: ModelValidator) -> None:
        cls._model_validators.append(model_validator)
        model_validator._register_for_model()

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

    def check_custom_validators(
            self,
            *,
            use_all: bool = False,
            use_caches: Optional[bool] = None,
    ) -> bool:
        for model_validator in self._model_validators:
            if use_all is True or model_validator.auto:
                if not model_validator.get_instance_validator(self).is_valid(use_cache=use_caches):
                    return False

        return True

    def get_custom_validator_results(
            self,
            *,
            use_all: bool = False,
            use_caches: Optional[bool] = None,
    ) -> dict[str, bool]:
        return {
            model_validator.get_property_name(): model_validator.get_instance_validator(self).is_valid(
                use_cache=use_caches)
            for model_validator in self._model_validators
            if use_all is True or model_validator.auto
        }

    def is_valid(
            self,
            *args,
            use_custom_validators: Optional[bool] = None,
            use_validator_caches: Optional[bool] = None,
            **kwargs,
    ) -> bool:
        try:
            super().full_clean(*args, **kwargs)
        except ValidationError:
            return False

        return use_custom_validators is False or self.check_custom_validators(
            use_all=use_custom_validators is True,
            use_caches=use_validator_caches,
        )

    @collect_validation_errors
    def full_clean(self, *args, use_custom_validators: Optional[bool] = None, **kwargs):
        try:
            super().full_clean(*args, **kwargs)
        except ValidationError as err:
            yield err

        if use_custom_validators is not False:
            yield from self.get_custom_validator_errors(use_all=use_custom_validators is True)

    def update_validator_caches(self, *, update_all: bool = False):
        for model_validator in self._model_validators:
            if model_validator.cache and (update_all is True or model_validator.auto_update_cache):
                model_validator.get_instance_validator(self).update_cache()

    def clear_validator_caches(self, *, clear_all: bool = False):
        for model_validator in self._model_validators:
            if model_validator.cache and (clear_all is True or model_validator.auto_update_cache):
                model_validator.get_instance_validator(self).clear_cache()

    def are_validation_results_cached(self):
        return all(
            model_validator.get_instance_validator(self).is_cached()
            for model_validator in self._model_validators
            if model_validator.cache
        )

    def save(self, *args, update_validator_caches: Optional[bool] = None, **kwargs):
        if update_validator_caches is not False:
            self.update_validator_caches(update_all=update_validator_caches is True)

        super().save(*args, **kwargs)

    @classmethod
    def update_validator_caches_globally(cls, queryset: Optional[QuerySet] = None, *, update_all: bool = False):
        for model_validator in cls._model_validators:
            if model_validator.cache and (update_all is True or model_validator.auto_update_cache):
                model_validator.update_cache(queryset)

    @classmethod
    def clear_validator_caches_globally(cls, queryset: Optional[QuerySet] = None, *, clear_all: bool = False):
        if queryset is None:
            queryset = cls.objects.all()

        fields = [
            model_validator.get_property_name()
            for model_validator in cls._model_validators
            if model_validator.cache and (clear_all is True or model_validator.auto_update_cache)
        ]

        queryset.update(**{field: None for field in fields})

    @classmethod
    def get_are_validation_results_cached_condition(cls) -> Q:
        condition = ~Q(pk__in=[])

        for model_validator in cls._model_validators:
            if model_validator.cache:
                condition &= model_validator.get_is_cached_condition()

        return condition

    @classmethod
    def are_validation_results_cached_globally(cls, queryset: Optional[QuerySet] = None) -> bool:
        if queryset is None:
            queryset = cls.objects.all()

        return queryset.filter(cls.get_are_validation_results_cached_condition()).exists()

    @classmethod
    def get_custom_validity_condition(cls) -> Q:
        condition = ~Q(pk__in=[])

        for model_validator in cls._model_validators:
            if model_validator.cache:
                condition &= model_validator.get_is_valid_condition()

        return condition

    @classmethod
    def check_custom_validators_globally(cls, queryset: Optional[QuerySet] = None) -> bool:
        if queryset is None:
            queryset = cls.objects.all()

        return queryset.filter(cls.get_custom_validity_condition()).exists()

    class Meta:
        abstract = True
