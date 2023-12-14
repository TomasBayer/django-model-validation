# django-model-validation

[![PyPI - Version](https://img.shields.io/pypi/v/django-model-validation)](https://pypi.org/project/django-model-validation/)

`django-model-validation` simplifies custom data validation for Django models.

## Quick Navigation

- [Features](#Features)
- [Installation](#Installation)
- [Example](#Example)
- [Full Usage](#FullUsage)
- [License](#License)

## Features

* Simple validator definition
* Validators are automatically executed and errors accumulated
* Adds a boolean property for validity checking that can optionally be cached in the database.
* Numerous helper functions for filtering by validity

## Installation

Requires Python version 3.9 or higher, Django version 3.2 or higher and pip.

```bash
pip install django-model-validation
```

Add 'django_model_validation' to your `INSTALLED_APPS` setting.

```python
INSTALLED_APPS = [
    ...
    'django_model_validation',
]
```

## Example

Replace the Django's `Model` base class by `ValidatingModel` and annotate a validation method with the `@validator`
decorator.

```python
from django.db import models
from django_model_validation.models import ValidatingModel, validator


class Person(ValidatingModel):
    date_of_birth = models.DateField()
    date_of_death = models.DateField(blank=True, null=True)
    is_alive = models.BooleanField(default=True)

    @validator
    def validate_biographical_data(self):
        if self.date_of_death is not None and self.is_alive:
            return "A date of death should not be set if the person is alive."
```

The `validate_biographical_data` function is now automatically executed when attempting to save the model from a form.
In case of failure, it raises
a [`ValidationError`](https://docs.djangoproject.com/en/5.0/ref/exceptions/#django.core.exceptions.ValidationError)
encapsulating the error message.

A model may have multiple custom validators. They all get executed, and if any of them raise errors, these, along
with any other validation errors are combined into a single `ValidationError`.

## Full Usage

### Writing validators

For convenience, instead of raising a `ValidationError`, custom validators may return any of the following:

- a string containing an error message (as in the example above)
- a dictionary that maps field names to lists of strings, or `ValidationError` objects
- a `ValidationError`
- a list (or any iterable) containing any of the above types, even mixed, or
- a boolean indicating validation success.

Validation is considered successful only if the method does not raise an exception and, either returns nothing or
returns `True`.

Returning iterables is particularly useful, as it allows validators to be written as
a [generator functions](https://wiki.python.org/moin/Generators), simplifying the code when multiple validations are
performed in a single function.

Examples:

```python
@validator
def validate_biographical_data(self):
    if self.date_of_death is not None:
        if self.is_alive:
            yield "A date of death should not be set if the person is alive."
        if self.date_of_death < self.date_of_birth:
            yield ValidationError("Date of death should not be before the date of birth.")
        if self.date_of_death > date.today():
            yield {"date_of_death": "Date of death should not be in the future."}


@validator
def validate_completeness(self):
    if self.date_of_birth > date.today():
        return {"date_of_death": "If the person is not alive, please provide a date of death."}

```

### Triggering validations manually

Custom validators are triggered during Django's standard validation process (i.e., as part of the `full_clean` method).
While this process is automatically invoked by model forms, it is not automatic when manually creating or updating an
object using, e.g., `save()`. In this case, it's necessary to call `full_clean` manually before saving.

To manually execute only the custom validators, call `run_custom_validators()` instead of `full_clean()`.

To manually execute a specific custom validator only, simply execute the decorated method. If the validation fails, the
decorator ensures the method raises a `ValidationError` containing all returned errors (if any).

Additionally, the decorator introduces some convenience functions to the method object:

```python
person = Person(...)

person.validate_completeness.get_validation_error()  # Returns the ValidationError instead of raising it.
person.validate_completeness.is_valid()  # Runs the validation and returns a bool indicating validation success.
```

Boolean validity checking can be simplified by specifying the `property_name` option:

```python
@validator(property_name='is_data_complete')
def validate_completeness(self):
    if self.date_of_birth > date.today():
        return {"date_of_death": "If the person is not alive, please provide a date of death."}
```

This sets up a model property that, when accessed, internally runs the `is_valid` method of the validator, allowing easy
access to validity like this:

```python
if person.is_data_complete:
    ...
```

### Enable validity caching

To enable database caching for the validity property, set the `cache` option to `True` in the `@validator` decorator.
This creates a hidden boolean field on the model, storing the result of the validity check whenever the model is saved.

```python
@validator(cache=True, property_name='is_data_complete')
def validate_completeness(self):
    ...
```

With this configuration, subsequent access to the property or the `is_valid()` method won't trigger the validation but
instead return the cached result.

#### Caveats:

- If attributes are modified but the object is not saved, the validity cache won't update, potentially leading to an
  outdated result.
- When adding a validator with `cache=True` or modifying the `cache` option of an existing one, a database migration is
  necessary. This can be created automatically with `makemigrations`.
- The cache field is initially empty. Refer to the "Cache Maintenance" section on how to automatically populate it upon
  creation.
- It is advisable to set the `cache` option together with the `property_name` option. When specified, the property name
  serves as the field name. If no property name is set, a field name is generated automatically, but accessing the cache
  is then only possible using the `is_valid()` method.

### Analyse data validity

The validity cache can be used to filter querysets by validity according to specific or all validators. Since the
property name of a cached validator is a model field, it can simply be used to filter querysets. For added convenience,
several utility functions are available through the validator method when it's accessed through the model class.

```python
# Obtain filtered querysets
Person.validate_completeness.get_valid_objects()
Person.validate_completeness.get_invalid_objects()

# Retrieve a Q object for use in queryset filtering
Person.validate_completeness.get_is_valid_condition()

# Check if all objects are valid
Person.validate_completeness.is_all_valid()
```

Furthermore, the model class offers additional tools for analysing data validity across all cached validators
simultaneously.

```python
# Custom pre-filtered managers
Person.valid_objects.all()
Person.invalid_objects.all()

# Retrieve a Q object for use in queryset filtering
Person.get_custom_validity_condition()

# Checks if all custom validation passes for all objects
Person.check_custom_validators_globally()
```

### Cache maintenance

While the library handles caching automatically in most scenarios, here are instances where manual examination and
manipulation of the cache are helpful. The following provides a brief overview of available functions.

```python
person = Person(...)

# For a specific validator
person.validate_completeness.update_cache()
person.validate_completeness.clear_cache()
is_cached = person.validate_completeness.is_cached()
cached_result = person.validate_completeness.get_cache()

# For all custom validators at once
person.update_validator_caches()
person.clear_validator_caches()
person.are_validation_results_cached()

# For a specific validator and all objects in the database at once
Person.validate_completeness.update_cache()
Person.validate_completeness.clear_cache()
Person.validate_completeness.is_all_cached()
Person.validate_completeness.get_is_cached_condition()

# For all custom validators and all objects in the database at once
Person.update_validator_caches_globally()
Person.clear_validator_caches_globally()
Person.are_validation_results_cached_globally()
Person.get_are_validation_results_cached_condition()
```

Additionally, the cache of a specific validator (or all validators) can be updated within a migration. This proves
especially useful for initial population of a cache of a validator that is added to an existing model.

To do this, simply append the `UpdateModelValidatorCache` to the end of the operations list that adds the validation
cache field, listing the validators for which the cache should be updated.

```
operations = [
    ...,
    UpdateModelValidatorCache('MyModel', MyModel.validate_something, MyModel.validate_something_else)
]
```

Caution: This may call migrations to fail when validator code undergoes changes at a later stage. For instance,
introducing new fields and modifying an existing validator to accommodate them will result in migration failures, as the
validator code cannot be executed on previous model versions. If faced with such issues, consider removing
obsolete `UpdateModelValidatorCache` operations from old migrations. Alternatively, consider manually populating the
cache using `RunPython`.

### Disable automatic validation

To accept invalid data by default, set the `auto` option to `False`. This is particularly useful for cached validators
used to track data quality.

```python
@validator(auto=False)
def validate_completeness(self):
    ...
```

### Full configuration

All keyword arguments of the `@validator` decorator:

- `auto` (`bool`): If `True`, the validator will automatically run as part of the model's `full_clean` method.
  *Defaults to True.*
- `cache` (`bool`): If `True`, a `ModelValidatorCacheField` will be implicitly added to the model which will be used to
  store the validation result.
  *Defaults to False.*
- `auto_use_cache` (`bool`): If `True`, calling the `is_valid()` method or the validity property will automatically use
  the cached validation result if available.
  *Defaults to True.*
- `auto_update_cache` (`bool`): If `True`, the validator will automatically be executed and the cache updated
  accordingly when the model is saved using the `save()` method.
  *Defaults to True.*
- `property_name` (`str`, optional): Custom name for the boolean validity property associated with this validator.
  If the cache is enabled, this will be used as the name of the cache field, otherwise a name will be
  constructed. If the cache is disabled, this will be used as the name of a property of the model that acts
  as a proxy to the `is_valid()` method of this validator.
- `property_verbose_name` (`str`, optional)`: If set, this will be used as `verbose_name` for the cache field as well
  as for generic error messages.

## License

`django-model-validation` is distributed under the terms of the MIT License.
