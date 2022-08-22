from django.db.models import BooleanField


class ModelValidatorCacheField(BooleanField):

    def __init__(self, verbose_name=None, **kwargs):
        # Store original for deconstruction and set default to True if not given
        self._has_null = 'null' in kwargs
        kwargs.setdefault('null', True)

        self._has_editable = 'editable' in kwargs
        kwargs.setdefault('editable', False)

        super().__init__(verbose_name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()

        if not self._has_null and 'null' in kwargs:
            del kwargs['null']

        if not self._has_editable and 'editable' in kwargs:
            del kwargs['editable']

        return name, path, args, kwargs
