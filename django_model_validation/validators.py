from dataclasses import dataclass, field
from types import GeneratorType
from typing import TYPE_CHECKING, Callable, Optional, Type

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Q, QuerySet

from django_model_validation.cache_field import ModelValidatorCacheField

if TYPE_CHECKING:
    from django_model_validation.models import ValidatingModel


class ValidatorHasNoCacheError(Exception):
    pass


@dataclass
class ModelInstanceValidator:
    """
    Represents the enhanced validator method of a Django model for a specific model instance.

    Attributes:
        model_validator (ModelValidator): The associated `ModelValidator` containing the validator method.
        model_instance: The instance of the Django model being validated.
    """
    model_validator: 'ModelValidator'
    model_instance: 'ValidatingModel'

    def _get_validation_error(self) -> Optional[ValidationError]:
        try:
            result = self.model_validator.method(self.model_instance)

            if isinstance(result, bool):
                if not result:
                    return ValidationError(
                        f"The validator \"{self.model_validator.get_property_verbose_name()}\" failed.",
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
        """
        Performs the validation on the model instance and returns a `ValidationError` if the validation fails.

        Args:
            update_cache (bool): If `True` and this validator has a cache, updates the cache with the validation
                result before returning it.
                *Defaults to True.*

        Returns:
            a `ValidationError` if the validation fails and `None` otherwise.
        """
        validation_error = self._get_validation_error()

        if self.model_validator.cache and update_cache:
            setattr(
                self.model_instance,
                self.model_validator.get_property_name(),
                validation_error is None,
            )

        return validation_error

    def validate(self, *, update_cache: bool = True) -> None:
        """
        Performs the validation on the model instance and raises a `ValidationError` if the validation fails.

        Args:
            update_cache (bool): If `True` and this validator has a cache, updates the cache with the validation
                result before returning it.
                *Defaults to True.*

        Raises:
            ValidationError: if the validation fails
        """
        validation_error = self.get_validation_error(update_cache=update_cache)

        if validation_error is not None:
            raise validation_error

    def is_valid(self, *, use_cache: Optional[bool] = None, update_cache: bool = True) -> bool:
        """
        Checks whether the validation succeeds on the model instance.

        Args:
            use_cache (bool, optional): Determines whether the cached value may be returned instead of running the
                validator. If this is `None`, this will be instead decided by the `auto_use_cache` option of this
                validator.
            update_cache (bool): If `True` and this validator has a cache, updates the cache with the validation
                result before returning it.

        Returns:
            bool: `True` if the validation succeeds, `False` otherwise.
        """
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
        """
        Checks if the validation result cache contains a value.

        Returns:
            bool: True if the validation result is cached, False otherwise.

        Raises:
            ValidatorHasNoCacheError: if the validator has no cache.
        """
        return self.get_cache() is not None

    def get_cache(self) -> Optional[bool]:
        """
        Retrieves the cached validation result.

        Returns:
            The cached boolean validation result is present or `None` otherwise.

        Raises:
            ValidatorHasNoCacheError: if the validator has no cache.
        """
        try:
            return getattr(self.model_instance, self.model_validator.get_property_name())
        except AttributeError as err:
            raise ValidatorHasNoCacheError() from err

    def update_cache(self) -> None:
        """
        Runs this validation on the modal instance and updates the cached result accordingly.

        Raises:
            ValidatorHasNoCacheError: if the validator has no cache.
        """
        try:
            return setattr(self.model_instance, self.model_validator.get_property_name(),
                           self.is_valid(use_cache=False))
        except AttributeError as err:
            raise ValidatorHasNoCacheError() from err

    def clear_cache(self) -> None:
        """
        Clears the cached validation result.

        Raises:
            ValidatorHasNoCacheError: if the validator has no cache.
        """
        try:
            return setattr(self.model_instance, self.model_validator.get_property_name(), None)
        except AttributeError as err:
            raise ValidatorHasNoCacheError() from err

    def __call__(self, *args, **kwargs) -> None:
        self.validate(*args, **kwargs)


@dataclass
class IsValidProxy:
    validator: 'ModelValidator'

    def __get__(self, instance, owner):
        if instance is not None:
            return self.validator.get_instance_validator(instance).is_valid()
        else:
            raise AttributeError("This attribute can only be access from an instance.")


@dataclass
class ModelValidator:
    """
    Represents an enhanced validator method of a Django model.
    """
    method: Callable
    auto: bool
    cache: bool
    auto_use_cache: bool
    auto_update_cache: bool
    property_name: Optional[str]
    property_verbose_name: Optional[str]

    model_type: Type['ValidatingModel'] = field(init=False, default=None)

    @property
    def name(self) -> str:
        return self.method.__name__

    def get_instance_validator(self, obj: 'ValidatingModel') -> ModelInstanceValidator:
        return ModelInstanceValidator(self, obj)

    def get_property_name(self) -> str:
        """
        Returns the custom name of the boolean validity property associated with the validator or constructs one from
        the method name if this validator has no custom property name.
        """
        if self.property_name is None:
            return f'is_{self.name}_successful'
        else:
            return self.property_name

    def get_property_verbose_name(self) -> str:
        """
        Returns the custom verbose name of the boolean validity property associated with the validator or returns the
        property name if this validator has no custom verbose property name.
        """
        if self.property_verbose_name is None:
            return self.get_property_name()
        else:
            return self.property_verbose_name

    def _register_for_model(self) -> None:
        if self.cache:
            try:
                _field = self.model_type._meta.get_field(self.get_property_name())
            except FieldDoesNotExist:
                self.model_type.add_to_class(
                    self.get_property_name(),
                    ModelValidatorCacheField(verbose_name=self.property_verbose_name),
                )
        elif self.property_name is not None:
            setattr(self.model_type, self.get_property_name(), IsValidProxy(self))

    def get_is_valid_condition(self) -> Q:
        """
        Returns a `Q` object for checking if objects are valid based on the cached result.
        """
        if self.cache:
            return Q(**{self.get_property_name(): True})
        else:
            raise ValidatorHasNoCacheError()

    def get_is_invalid_condition(self, *, include_unknown_validity: bool = False) -> Q:
        """
        Returns a `Q` object for checking if objects are invalid based on the cached result.

        Args:
            include_unknown_validity (`bool`, optional): If `True`, objects without cached validity will be considered
                invalid.
                *Defaults to False.*
        """
        if self.cache:
            if include_unknown_validity:
                return ~Q(**{self.get_property_name(): True})
            else:
                return Q(**{self.get_property_name(): False})
        else:
            raise ValidatorHasNoCacheError()

    def get_is_cached_condition(self) -> Q:
        """
        Returns a `Q` object for checking if the validator cache is non-empty.
        """
        if self.cache:
            return Q(**{f'{self.get_property_name()}__isnull': False})
        else:
            raise ValidatorHasNoCacheError()

    def get_valid_objects(self, queryset: Optional[QuerySet] = None) -> QuerySet:
        """
        Returns a `QuerySet` of objects that are considered valid according to the cached results of this validation
        method.

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.

        Returns:
            QuerySet: A `QuerySet` containing valid objects.
        """
        if queryset is None:
            queryset = self.model_type.objects

        return queryset.filter(self.get_is_valid_condition())

    def get_invalid_objects(
            self,
            queryset: Optional[QuerySet] = None,
            *,
            include_unknown_validity: bool = False,
    ) -> QuerySet:
        """
        Returns a `QuerySet` of objects that are considered invalid according to the cached results of this validation
        method.

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.
            include_unknown_validity (`bool`, optional): If `True`, objects without cached validity will be considered
                invalid.
                *Defaults to False.*

        Returns:
            QuerySet: A `QuerySet` containing invalid objects.
        """
        if queryset is None:
            queryset = self.model_type.objects

        return queryset.filter(self.get_is_invalid_condition(include_unknown_validity=include_unknown_validity))

    def is_all_valid(self, queryset: Optional[QuerySet] = None) -> bool:
        """
        Checks whether all objects are valid according to the cached results of this validation method.

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.

        Returns:
            `True` if all objects are valid, `False` if at least one object is not valid.
        """
        if queryset is None:
            queryset = self.model_type.objects.all()

        return self.get_invalid_objects(queryset).exists()

    def is_all_cached(self, queryset: Optional[QuerySet] = None) -> bool:
        """
        Checks whether all objects have a cached validation result.

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.

        Returns:
            `True` if all objects have a cached validation result, `False` if at least one object has no cached result.
        """
        if queryset is None:
            queryset = self.model_type.objects.all()

        return not queryset.filter(~self.get_is_cached_condition()).exists()

    def update_cache(self, queryset: Optional[QuerySet] = None) -> None:
        """
        Runs the validation on all objects in the database (or a subset thereof) and updates the cached results
        accordingly.

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.
        """
        if not self.cache:
            raise ValidatorHasNoCacheError()

        if queryset is None:
            queryset = self.model_type.objects.all()

        for obj in queryset:
            self.get_instance_validator(obj).update_cache()
            obj.save(update_validator_caches=False)

    def clear_cache(self, queryset: Optional[QuerySet] = None) -> None:
        """
        Clears the cached validation results of all objects in the database (or a subset thereof).

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.
        """
        if not self.cache:
            raise ValidatorHasNoCacheError()

        if queryset is None:
            queryset = self.model_type.objects.all()

        queryset.update(**{self.get_property_name(): None})

    def __set_name__(self, model_type: Type['ValidatingModel'], name: str):
        self.model_type = model_type

    def __get__(self, instance: 'ValidatingModel', cls=None):
        if instance is None:
            return self
        else:
            return self.get_instance_validator(instance)
