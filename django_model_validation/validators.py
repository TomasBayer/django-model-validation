from dataclasses import dataclass, field
from types import GeneratorType
from typing import TYPE_CHECKING, Callable, Optional, Type

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from django_model_validation.cache_field import ModelValidatorCacheField

if TYPE_CHECKING:
    from django_model_validation.models import ValidatingModel


class ValidatorHasNoCacheError(Exception):
    pass


@dataclass
class ModelInstanceValidator:
    model_validator: 'ModelValidator'
    model_instance: 'ValidatingModel'

    def _get_validation_error(self) -> Optional[ValidationError]:
        try:
            result = self.model_validator.method(self.model_instance)

            if isinstance(result, bool):
                if not result:
                    return ValidationError(
                        f"The validator \"{self.model_validator.get_cache_field_verbose_name()}\" failed.",
                    )
                else:
                    return None

            if isinstance(result, GeneratorType):
                result = list(result)

            if result:
                return ValidationError(result)
        except ValidationError as err:
            return err

        return None

    def get_validation_error(self, *, update_cache: bool = True) -> Optional[ValidationError]:
        validation_error = self._get_validation_error()

        if self.model_validator.cache and update_cache:
            setattr(
                self.model_instance,
                self.model_validator.get_cache_field_name(),
                validation_error is None,
            )

        return validation_error

    def validate(self, *, update_cache: bool = True) -> None:
        validation_error = self.get_validation_error(update_cache=update_cache)

        if validation_error is not None:
            raise validation_error

    def is_valid(self, *, use_cache: Optional[bool] = None, update_cache: bool = True) -> bool:
        if self.model_validator.cache:
            if use_cache is None:
                use_cache = self.model_validator.auto_use_cache

            if use_cache:
                cache_value = self.get_cache()
                if cache_value is not None:
                    return cache_value

        try:
            self.validate(update_cache=update_cache)
            return True
        except ValidationError:
            return False

    def is_cached(self) -> bool:
        return self.get_cache() is not None

    def get_cache(self) -> Optional[bool]:
        try:
            return getattr(self.model_instance, self.model_validator.get_cache_field_name())
        except AttributeError as err:
            raise ValidatorHasNoCacheError() from err

    def update_cache(self) -> None:
        try:
            return setattr(self.model_instance, self.model_validator.get_cache_field_name(),
                           self.is_valid(use_cache=False))
        except AttributeError as err:
            raise ValidatorHasNoCacheError() from err

    def clear_cache(self) -> None:
        try:
            return setattr(self.model_instance, self.model_validator.get_cache_field_name(), None)
        except AttributeError as err:
            raise ValidatorHasNoCacheError() from err

    def __call__(self, *args, **kwargs) -> None:
        self.validate(*args, **kwargs)


@dataclass
class ModelValidator:
    method: Callable
    auto: bool
    cache: bool
    auto_use_cache: bool
    auto_update_cache: bool
    cache_field_name: Optional[str]
    cache_field_verbose_name: Optional[str]

    model_type: Type['ValidatingModel'] = field(init=False, default=None)

    @property
    def name(self) -> str:
        return self.method.__name__

    def get_instance_validator(self, obj: 'ValidatingModel') -> ModelInstanceValidator:
        return ModelInstanceValidator(self, obj)

    def get_cache_field_name(self) -> str:
        if self.cache_field_name is None:
            return f'is_{self.name}_successful'
        else:
            return self.cache_field_name

    def get_cache_field_verbose_name(self) -> str:
        if self.cache_field_verbose_name is None:
            return self.get_cache_field_name()
        else:
            return self.cache_field_verbose_name

    def _register_for_model(self) -> None:
        if self.cache:
            self.model_type.add_to_class(
                self.get_cache_field_name(),
                ModelValidatorCacheField(verbose_name=self.cache_field_verbose_name),
            )

    def get_is_valid_condition(self) -> Q:
        if self.cache:
            return Q(**{self.get_cache_field_name(): True})
        else:
            raise ValidatorHasNoCacheError()

    def get_is_invalid_condition(self, *, include_unknown_validity: bool = False) -> Q:
        if self.cache:
            if include_unknown_validity:
                return ~Q(**{self.get_cache_field_name(): True})
            else:
                return Q(**{self.get_cache_field_name(): False})
        else:
            raise ValidatorHasNoCacheError()

    def get_is_cached_condition(self) -> Q:
        if self.cache:
            return Q(**{f'{self.get_cache_field_name()}__isnull': False})
        else:
            raise ValidatorHasNoCacheError()

    def get_valid_objects(self, queryset: Optional[QuerySet] = None) -> QuerySet:
        if queryset is None:
            queryset = self.model_type.objects

        return queryset.filter(self.get_is_valid_condition())

    def get_invalid_objects(
            self,
            queryset: Optional[QuerySet] = None,
            *,
            include_unknown_validity: bool = False,
    ) -> QuerySet:
        if queryset is None:
            queryset = self.model_type.objects

        return queryset.filter(self.get_is_invalid_condition(include_unknown_validity=include_unknown_validity))

    def is_all_valid(self, queryset: Optional[QuerySet] = None) -> bool:
        if queryset is None:
            queryset = self.model_type.objects.all()

        return self.get_invalid_objects(queryset).exists()

    def is_all_cached(self, queryset: Optional[QuerySet] = None) -> bool:
        if queryset is None:
            queryset = self.model_type.objects.all()

        return not queryset.filter(~self.get_is_cached_condition()).exists()

    def update_cache(self, queryset: Optional[QuerySet] = None) -> None:
        if not self.cache:
            raise ValidatorHasNoCacheError()

        if queryset is None:
            queryset = self.model_type.objects.all()

        for obj in queryset:
            self.get_instance_validator(obj).update_cache()
            obj.save(update_validator_caches=False)

    def clear_cache(self, queryset: Optional[QuerySet] = None) -> None:
        if not self.cache:
            raise ValidatorHasNoCacheError()

        if queryset is None:
            queryset = self.model_type.objects.all()

        queryset.update(**{self.get_cache_field_name(): None})

    def __set_name__(self, model_type: Type['ValidatingModel'], name: str):
        self.model_type = model_type

    def __get__(self, instance: 'ValidatingModel', cls=None):
        if instance is None:
            return self
        else:
            return self.get_instance_validator(instance)
