from __future__ import unicode_literals
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from uuid import uuid4

import nested_intervals
from nested_intervals.models import NestedIntervalsModel
from nested_intervals.managers import NestedIntervalsManager
from django.db.models.query import QuerySet


class CustomTreeQueryset(QuerySet):

    def custom_method(self):
        pass


class CustomNestedIntervalsManager(NestedIntervalsManager):

    def get_queryset(self):
        return CustomTreeQueryset(model=self.model, using=self._db)


@python_2_unicode_compatible
class Category(NestedIntervalsModel):
    name = models.CharField(max_length=50)
    category_uuid = models.CharField(max_length=50, unique=True, null=True)

    def __str__(self):
        return self.name

    def delete(self):
        super(Category, self).delete()
    delete.alters_data = True


class Tree(NestedIntervalsModel):
    pass


@python_2_unicode_compatible
class Item(models.Model):

    name = models.CharField(max_length=100)
    category_fk = models.ForeignKey(
        'Category', to_field='category_uuid', null=True,
        related_name='items_by_fk', on_delete=models.CASCADE)
    category_pk = models.ForeignKey(
        'Category', null=True, related_name='items_by_pk',
        on_delete=models.CASCADE)

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Genre(NestedIntervalsModel):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Game(models.Model):
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE)
    genres_m2m = models.ManyToManyField(Genre, related_name='games_m2m')
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Insert(NestedIntervalsModel):
    pass


@python_2_unicode_compatible
class MultiOrder(NestedIntervalsModel):
    name = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    date = models.DateField()

    def __str__(self):
        return self.name


class UUIDNode(NestedIntervalsModel):
    uuid = models.UUIDField(primary_key=True, default=uuid4)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Tree(NestedIntervalsModel):
    pass



@python_2_unicode_compatible
class Person(NestedIntervalsModel):
    name = models.CharField(max_length=50)

    # just testing it's actually possible to override the tree manager
    objects = CustomNestedIntervalsManager()

    def __str__(self):
        return self.name


class Student(Person):
    type = models.CharField(max_length=50)


@python_2_unicode_compatible
class CustomPKName(NestedIntervalsModel):
    my_id = models.AutoField(db_column='my_custom_name', primary_key=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class ReferencingModel(models.Model):
    fk = models.ForeignKey(Category, related_name='+', on_delete=models.CASCADE)
    one = models.OneToOneField(Category, related_name='+', on_delete=models.CASCADE)
    m2m = models.ManyToManyField(Category, related_name='+')


# for testing various types of inheritance:

# 1. multi-table inheritance, with nested_intervals fields on base class.

class MultiTableInheritanceA1(NestedIntervalsModel):
    pass


class MultiTableInheritanceA2(MultiTableInheritanceA1):
    name = models.CharField(max_length=50)


# 2. multi-table inheritance, with nested_intervals fields on child class.

class MultiTableInheritanceB1(NestedIntervalsModel):
    name = models.CharField(max_length=50)


class MultiTableInheritanceB2(MultiTableInheritanceB1):
    pass


# 3. abstract models

class AbstractModel(NestedIntervalsModel):
    ghosts = models.CharField(max_length=50)

    class Meta:
        abstract = True


class ConcreteModel(AbstractModel):
    name = models.CharField(max_length=50)


class AbstractConcreteAbstract(ConcreteModel):
    # abstract --> concrete --> abstract

    class Meta:
        abstract = True


class ConcreteAbstractConcreteAbstract(ConcreteModel):
    # concrete --> abstract --> concrete --> abstract
    pass


class ConcreteConcrete(ConcreteModel):
    # another subclass (concrete this time) of the root concrete model
    pass


# 4. proxy models

class SingleProxyModel(ConcreteModel):
    objects = CustomNestedIntervalsManager()

    class Meta:
        proxy = True


class DoubleProxyModel(SingleProxyModel):

    class Meta:
        proxy = True


# Default manager
class MultipleManager(NestedIntervalsManager):
    def get_queryset(self):
        return super(MultipleManager, self).get_queryset().exclude(published=False)


class MultipleManagerModel(NestedIntervalsModel):
    published = models.BooleanField()

    objects = NestedIntervalsManager()
    foo_objects = MultipleManager()


class AutoNowDateFieldModel(NestedIntervalsModel):
    now = models.DateTimeField(auto_now_add=True)


class Book(NestedIntervalsModel):
    name = models.CharField(max_length=50)
    fk = models.ForeignKey(
        Category, null=True, blank=True, related_name='books_fk',
        on_delete=models.CASCADE)
    m2m = models.ManyToManyField(Category, blank=True, related_name='books_m2m')
