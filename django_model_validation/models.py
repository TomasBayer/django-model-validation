from typing import Callable, Iterator, Optional, Type

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Manager, Q, QuerySet
from django.db.models.base import ModelBase

from django_model_validation.utils import collect_validation_errors
from django_model_validation.validators import ModelValidator


def validator(
        function: Optional[Callable] = None,
        *,
        auto: bool = True,
        cache: bool = False,
        auto_use_cache: bool = True,
        auto_update_cache: bool = True,
        property_name: Optional[str] = None,
        property_verbose_name: Optional[str] = None,
):
    """
    Decorator that enhances a method of a Django model that performs any custom validation of the data.

    The decorated method must be a validator in the following sense: It must either raise a `ValidationError`,
    return a `ValidationError`, return an error message, return a dictionary that maps field names to lists of
    `ValidationError`s or error messages, or return a list (or any iterable) containing any of the previous. In case of
    a successful validation, it should raise no `ValidationError` and return nothing.

    The decorator ensures that the validation function is automatically executed as part of the instance 'cleaning'
    process. Optionally, it can cache the boolean validation result in the database and updates the cache whenever the
    data is changed.

    Invoking the decorated method will execute the validation and, should it return anything, raise a `ValidationError`
    wrapping all outputs of any type. The decorator also adds a couple of convenience methods to the method object of an
    instance of the model:

    - is_valid(): Returns `True` if the validation succeeds and `False` otherwise. May return the result from the cache.
    - get_validation_error(): Returns the `ValidationError` if the validation fails and `None` otherwise.
    - validate(): Runs the validation and raises an `ValidationError` if the validation fails. This is the same as
      calling the validator method directly.
    - update_cache(): Runs the validation and stores the result in the cache field.
    - clear_cache(): Clears the validation result from the cache field.
    - is_cached(): Returns `True` if the cache field contains a validation result and `False` otherwise.
    - get_cache(): Returns the boolean validation result if the cache is present and `None` otherwise.

    It also adds convenience methods to the method object of the model class:

    - update_cache(): Updates the validation cache for all objects in the database.
    - clear_cache(): Clears the validation cache for all objects in the database.
    - get_is_valid_condition(): Returns a `Q` object for filtering `QuerySets` by validity according to the cache.
    - get_is_cache_empty_condition(): Returns a `Q` object for filtering `QuerySets` by cache emptiness.
    - get_valid_objects(): Returns a queryset filtered by valid objects (according to the cache).
    - get_invalid_objects(): Returns a queryset filtered by invalid objects (according to the cache).
    - is_all_valid(): Checks whether all objects are valid (according to the cache).
    - is_all_cached(): Checks whether all objects have a cached valiation result.

    This decorator can be used with or without parameters.

    Args:
        auto (bool): If True, the validator will automatically run as part of the model's `full_clean` method.
            *Defaults to True.*
        cache (bool): If True, a `ModelValidatorCacheField` will be implicitly added to the model which will be used to
            store the validation result.
            *Defaults to False.*
        auto_use_cache (bool): If True, calling the is_valid() method or the validity property will automatically use
            the cached validation result if available.
            *Defaults to True.*
        auto_update_cache (bool): If True, the validator will automatically be executed and the cache updated
            accordingly when the model is saved using the save() method.
            *Defaults to True.*
        property_name (str, optional): Custom name for the boolean validity property associated with this validator.
            If the cache is enabled, this will be used as the name of the cache field, otherwise a name will be
            constructed. If the cache is disabled, this will be used as the name of a property of the model that acts
             as a proxy to the is_valid() method of this validator.
        property_verbose_name (str, optional): If set, this will be used as `verbose_name` for the cache field as well
            as for generic error messages.

    Example::

        class PersonWithAlliterativeName(models.Model):
            first_name = models.CharField(max_length=30)
            last_name = models.CharField(max_length=30)

            @validator
            def validate_alliteration(self):
                if self.first_name[0] != self.last_name[0]:
                    return "The first and the last name start with a different letter."
    """

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

    if function is None:
        return decorator
    else:
        return decorator(function)


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
    """
    Base class for Django models with validators.

    This class keeps track of all methods annotated with the `@validator` decorator and provides the necessary
    functionality for them to operate.
    """

    objects = ValidatingModelManager()
    valid_objects = ValidatingModelManager(exclude_valid=True)
    invalid_objects = ValidatingModelManager(exclude_invalid=True)

    @classmethod
    def _register_validator(cls, model_validator: ModelValidator) -> None:
        cls._model_validators.append(model_validator)
        model_validator._register_for_model()

    def get_custom_validator_errors(self, *, use_all: bool = False) -> Iterator[ValidationError]:
        """
        Returns an iterator that runs all custom validators and yields all `ValidationErrors`.

        Args:
            use_all (bool, optional): If `True`, all custom validators are executed. If `False`, only custom validators
                with the `auto` option set are executed.
                *Defaults to False.*
        """
        for model_validator in self._model_validators:
            if use_all is True or model_validator.auto:
                try:
                    model_validator.get_instance_validator(self).validate()
                except ValidationError as err:
                    yield err

    def run_custom_validators(self, *, use_all: bool = False) -> None:
        """
        Runs all custom validators.

        Args:
            use_all (bool, optional): If `True`, all custom validators are executed. If `False`, only custom validators
                with the `auto` option set are executed.
                *Defaults to False.*

        Raises:
            ValidationError: If any of the custom validators raise a `ValidationError`.
        """
        errors = list(self.get_custom_validator_errors(use_all=use_all))
        if errors:
            raise ValidationError(errors)

    def check_custom_validators(
            self,
            *,
            use_all: bool = False,
            use_caches: Optional[bool] = None,
    ) -> bool:
        """
        Checks whether all custom validators succeed.

        Args:
            use_all (bool, optional): If `True`, all custom validators are executed. If `False`, only custom validators
                with the `auto` option set are executed.
                *Defaults to False.*
            use_caches (bool, optional): Determines whether cached values may be used instead of running the
                validators. If this is `None`, this will be instead decided by the `auto_use_cache` option of the
                individual validators.

        Returns:
            bool: `True` if all validations succeed, `False` otherwise.
        """
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
        """
        Returns an overview of all custom validators with their validation results.

        Args:
            use_all (bool, optional): If `True`, all custom validators are executed. If `False`, only custom validators
                with the `auto` option set are executed.
                *Defaults to False.*
            use_caches (bool, optional): Determines whether cached values may be used instead of running the
                validators. If this is `None`, this will be instead decided by the `auto_use_cache` option of the
                individual validators.

        Returns:
            dict: A dictionary mapping the validator property names to their boolean validation results.
        """
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
        """
        Runs the default `full_clean` method as well as the custom validators and returns `True` if and only if all
        validations succeed.

        All provided arguments, excluding `use_custom_validators` and `use_validator_caches`, are passed to the default
        `full_clean` method.

        Args:
            use_custom_validators (bool, optional): Determines whether custom validators are executed. If `None`, only
                custom validators with the `auto` option set are executed. If `True`, all custom validators are
                executed. If `False`, no custom validator is executed.
                *Defaults to None.*
            use_validator_caches (bool, optional): Determines whether cached values will be used instead of running the
                validators. If this is `None`, this will be instead decided by the `auto_use_cache` option of the
                individual validators.

        Returns:
            bool: `True` if all validations succeed, `False` otherwise.
        """
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
        """
        Runs the default `full_clean` method as well as the custom validators and combines potential validation errors
        into a single `ValidationError`.

        All provided arguments, excluding `use_custom_validators`, are passed to the default `full_clean` method.

        Args:
            use_custom_validators (bool, optional): Determines whether custom validators are executed. If `None`, only
                custom validators with the `auto` option set are executed. If `True`, all custom validators are
                executed. If `False`, no custom validator is executed.
                *Defaults to None.*

        Raises:
            ValidationError: If the default `full_clean` method or any of the custom validators raise a
                `ValidationError`.
        """
        try:
            super().full_clean(*args, **kwargs)
        except ValidationError as err:
            yield err

        if use_custom_validators is not False:
            yield from self.get_custom_validator_errors(use_all=use_custom_validators is True)

    def update_validator_caches(self, *, update_all: bool = False):
        """
        Runs all validators with caches on this modal instance and updates the cached results accordingly.

        Args:
            update_all (bool, optional): If `True`, all custom validators with caches are update. If `False`, only
                custom validators with cashes with the `auto_update_cache` option set are executed.
                *Defaults to False.*
        """
        for model_validator in self._model_validators:
            if model_validator.cache and (update_all is True or model_validator.auto_update_cache):
                model_validator.get_instance_validator(self).update_cache()

    def clear_validator_caches(self, *, clear_all: bool = False):
        """
        Clears all cached validation results.

        Args:
            clear_all (bool, optional): If `True`, all custom validators with caches are cleared. If `False`, only
                custom validators with cashes with the `auto_update_cache` option set are cleared.
                *Defaults to False.*
        """
        for model_validator in self._model_validators:
            if model_validator.cache and (clear_all is True or model_validator.auto_update_cache):
                model_validator.get_instance_validator(self).clear_cache()

    def are_validation_results_cached(self):
        """
        Checks whether all validation caches are non-empty.
        """
        return all(
            model_validator.get_instance_validator(self).is_cached()
            for model_validator in self._model_validators
            if model_validator.cache
        )

    def save(self, *args, update_validator_caches: Optional[bool] = None, **kwargs):
        """
        Updates all configured validation caches before running the default `save` method.

        All provided arguments, excluding `update_validator_caches`, are passed to the default `save` method.

        Args:
            update_validator_caches (bool, optional): If `None`, updates the caches of all validators that have a cache
                and are configured for automatic update on saving. If `True`, updates the caches of all validation
                methods that have a cache regardless of their automatic update setting. If `False`, does not update any
                caches at all.
                *Defaults to None.*
        """
        if update_validator_caches is not False:
            self.update_validator_caches(update_all=update_validator_caches is True)

        super().save(*args, **kwargs)

    @classmethod
    def update_validator_caches_globally(cls, queryset: Optional[QuerySet] = None, *, update_all: bool = False):
        """
        Runs all validators with caches on all objects in the database (or a subset thereof) and updates the
        cached results accordingly.

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.
            update_all (bool, optional): If `True`, all custom validators with caches are update. If `False`, only
                custom validators with cashes with the `auto_update_cache` option set are executed.
                *Defaults to False.*
        """
        for model_validator in cls._model_validators:
            if model_validator.cache and (update_all is True or model_validator.auto_update_cache):
                model_validator.update_cache(queryset)

    @classmethod
    def clear_validator_caches_globally(cls, queryset: Optional[QuerySet] = None, *, clear_all: bool = False):
        """
        Clears all cached validation results of all objects in the database (or a subset thereof).

        Args:
            queryset (`QuerySet`, optional): If provided, this `QuerySet` will be used as the source of objects,
                otherwise a `QuerySet` will be constructed by calling the `all()` method on the default manager.
            clear_all (bool, optional): If `True`, all custom validators with caches are cleared. If `False`, only
                custom validators with cashes with the `auto_update_cache` option set are cleared.
                *Defaults to False.*
        """
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
        """
        Returns a `Q` object for checking if all validation caches are non-empty.
        """
        condition = ~Q(pk__in=[])

        for model_validator in cls._model_validators:
            if model_validator.cache:
                condition &= model_validator.get_is_cached_condition()

        return condition

    @classmethod
    def are_validation_results_cached_globally(cls, queryset: Optional[QuerySet] = None) -> bool:
        """
        Checks if all validation caches of all objects are non-empty.
        """
        if queryset is None:
            queryset = cls.objects.all()

        return queryset.filter(cls.get_are_validation_results_cached_condition()).exists()

    @classmethod
    def get_custom_validity_condition(cls) -> Q:
        """
        Returns a `Q` object for checking if all custom validators with caches succeed according to cached results.
        """
        condition = ~Q(pk__in=[])

        for model_validator in cls._model_validators:
            if model_validator.cache:
                condition &= model_validator.get_is_valid_condition()

        return condition

    @classmethod
    def check_custom_validators_globally(cls, queryset: Optional[QuerySet] = None) -> bool:
        """
        Checks if all custom validators with caches succeed for all objects according to cached results.
        """
        if queryset is None:
            queryset = cls.objects.all()

        return queryset.filter(cls.get_custom_validity_condition()).exists()

    class Meta:
        abstract = True
