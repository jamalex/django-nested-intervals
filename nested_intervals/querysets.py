from django.db import models


class NestedIntervalsQuerySet(models.query.QuerySet):
    
    def get_descendants(self, *args, **kwargs):
        """
        Alias to `nested_intervals.managers.NestedIntervalsManager.get_queryset_descendants`.
        """
        return self.model.objects.get_queryset_descendants(self, *args, **kwargs)
    get_descendants.queryset_only = True

    def get_ancestors(self, *args, **kwargs):
        """
        Alias to `nested_intervals.managers.NestedIntervalsManager.get_queryset_ancestors`.
        """
        return self.model.objects.get_queryset_ancestors(self, *args, **kwargs)
    get_ancestors.queryset_only = True
