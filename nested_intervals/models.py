from __future__ import unicode_literals
from functools import reduce, wraps

from django.db import models, transaction
from django.db.models.base import ModelBase
from django.db.models.fields import AutoField
from django.db.models.query import F, Q

from django.utils import six

from .conf import DECIMAL_PLACES
from .exceptions import InvalidMove
from .managers import NestedIntervalsManager

def raise_if_unsaved(func):
    @wraps(func)
    def _fn(self, *args, **kwargs):
        if not self.pk:
            raise ValueError(
                'Cannot call %(function)s on unsaved %(class)s instances'
                % {'function': func.__name__, 'class': self.__class__.__name__}
            )
        return func(self, *args, **kwargs)
    return _fn


class NestedIntervalsModel(models.Model):
    """
    Base class for tree models.
    """

    left = models.DecimalField(max_digits=DECIMAL_PLACES+1, decimal_places=DECIMAL_PLACES)
    right = models.DecimalField(max_digits=DECIMAL_PLACES+1, decimal_places=DECIMAL_PLACES)
    level = models.PositiveIntegerField()
    tree_id = models.UUIDField()

    objects = NestedIntervalsManager()

    # holds False if the parent hasn't been changed, otherwise the new value
    _new_parent = False

    # track whether nested intervals fields have changed so we can avoid saving them unnecessarily
    _nested_intervals_fields_have_changed = False

    class Meta:
        abstract = True
        ordering = ['left']

    def __init__(self, *args, **kwargs):
        if "parent" in kwargs:
            self.parent = kwargs.pop("parent")
        if "parent_id" in kwargs:
            self.parent_id = kwargs.pop("parent_id")
        super(NestedIntervalsModel, self).__init__(*args, **kwargs)

    @property
    def _tree_manager(self):
        return type(self).objects

    @property
    def parent(self):
        # if a parent has been set since last save, return that value, or None if we've never saved
        if self._new_parent is not False or not self._is_saved():
            return self._new_parent or None
        # if we're at level 0, there is no parent
        if self.level == 0:
            return None
        # otherwise, compute a parent value from the database
        return self._tree_manager.filter(
            left__lt=self.left,
            right__gt=self.right,
            level=self.level-1,
            tree_id=self.tree_id,
        ).first()

    @parent.setter
    def parent(self, newparent):
        if newparent is not None and not newparent._is_saved():
            raise ValueError("Parent must be saved before you can attach a child to it")
        self._nested_intervals_fields_have_changed = True
        self._new_parent = newparent

    @property
    def parent_id(self):
        parent = self.parent
        return parent.id if parent else None

    @parent_id.setter
    def parent_id(self, newparent_id):
        self.parent = self._tree_manager.get(id=newparent_id)

    @property
    def children(self):
        return self.get_children()

    @raise_if_unsaved
    def get_ancestors(self, ascending=False, include_self=False):
        """
        Creates a ``QuerySet`` containing the ancestors of this model
        instance.

        This defaults to being in descending order (root ancestor first,
        immediate parent last); passing ``True`` for the ``ascending``
        argument will reverse the ordering (immediate parent first, root
        ancestor last).

        If ``include_self`` is ``True``, the ``QuerySet`` will also
        include this model instance.
        """
        if self.is_root_node():
            if include_self:
                # Filter on pk for efficiency.
                return self._tree_manager.filter(pk=self.pk)
            else:
                return self._tree_manager.none()
        else:
            
            if ascending:
                order_by = '-left'
            else:
                order_by = 'left'

            if include_self:
                return self._tree_manager.filter(
                    Q(
                        left__lte=self.left,
                        right__gte=self.right,
                        tree_id=self.tree_id,
                    ) | Q(
                        pk=self.pk,
                    )
                ).order_by(order_by)
            else:
                return self._tree_manager.filter(
                    left__lt=self.left,
                    right__gt=self.right,
                    tree_id=self.tree_id,
                ).exclude(pk=self.pk).order_by(order_by)

    @raise_if_unsaved
    def get_family(self):
        """
        Returns a ``QuerySet`` containing the ancestors, the model itself
        and the descendants, in tree order.
        """
        return self.get_ancestors(include_self=True) | self.get_descendants()

    @raise_if_unsaved
    def get_children(self):
        """
        Returns a ``QuerySet`` containing the immediate children of this
        model instance, in tree order.

        The benefit of using this method over the reverse relation
        provided by the ORM to the instance's children is that a
        database query can be avoided in the case where the instance is
        a leaf node (it has no children).

        If called from a template where the tree has been walked by the
        ``cache_tree_children`` filter, no database query is required.
        """

        return self.get_descendants().filter(level=self.level+1)

    @raise_if_unsaved
    def get_descendants(self, include_self=False):
        """
        Creates a ``QuerySet`` containing descendants of this model
        instance, in tree order.

        If ``include_self`` is ``True``, the ``QuerySet`` will also
        include this model instance.
        """
        if include_self:
            return self._tree_manager.filter(
                Q(
                    left__gte=self.left,
                    left__lte=self.right,
                    tree_id=self.tree_id,
                ) | Q(
                    pk=self.pk,
                )
            )
        else:
            return self._tree_manager.filter(
                left__gt=self.left,
                left__lt=self.right,
                tree_id=self.tree_id,
            ).exclude(pk=self.pk)

    def get_descendant_count(self):
        """
        Returns the number of descendants this model instance has.
        Note: this isn't as efficient as it is with MPTT, since we're using Decimals, not Integers.
        """
        return self.get_descendants().count()

    @raise_if_unsaved
    def get_leafnodes(self, include_self=False):
        """
        Creates a ``QuerySet`` containing leafnodes of this model
        instance, in tree order.

        If ``include_self`` is ``True``, the ``QuerySet`` will also
        include this model instance (if it is a leaf node)
        """
        raise NotImplementedError("Can't be easily done very efficiently with Nested Intervals")

    @raise_if_unsaved
    def get_next_sibling(self, *filter_args, **filter_kwargs):
        """
        Returns this model instance's next sibling in the tree, or
        ``None`` if it doesn't have a next sibling.
        """
        
        if self.is_root_node():
            return None

        return self.parent.get_children().filter(left__gt=self.right).filter(*filter_args, **filter_kwargs).first()

    @raise_if_unsaved
    def get_previous_sibling(self, *filter_args, **filter_kwargs):
        """
        Returns this model instance's previous sibling in the tree, or
        ``None`` if it doesn't have a previous sibling.
        """
        if self.is_root_node():
            return None

        return self.parent.get_children().filter(right__lt=self.left).filter(*filter_args, **filter_kwargs).last()

    @raise_if_unsaved
    def get_root(self):
        """
        Returns the root node of this model instance's tree.
        """
        if self.is_root_node():
            return self

        return self._tree_manager.filter(
            tree_id=self.tree_id,
            level=0,
        ).get()

    @raise_if_unsaved
    def get_siblings(self, include_self=False):
        """
        Creates a ``QuerySet`` containing siblings of this model
        instance. Root nodes are considered to be siblings of other root
        nodes.

        If ``include_self`` is ``True``, the ``QuerySet`` will also
        include this model instance.
        """
        if self.is_root_node():
            if include_self:
                # Filter on pk for efficiency.
                return self._tree_manager.filter(pk=self.pk)
            else:
                return self._tree_manager.none()

        qs = self.parent.get_children()
        if not include_self:
            qs = qs.exclude(pk=self.pk)
        return qs

    def get_level(self):
        """
        Returns the level of this node (distance from root)
        """
        return self.level

    def insert_at(self, target, position='first-child', save=False):
        """
        Convenience method for calling ``NestedIntervalManager.insert_node`` with this
        model instance.
        """
        self._tree_manager.insert_node(self, target, position, save)

    def is_child_node(self):
        """
        Returns ``True`` if this model instance is a child node, ``False``
        otherwise.
        """
        return not self.is_root_node()

    def is_leaf_node(self):
        """
        Returns ``True`` if this model instance is a leaf node (it has no
        children), ``False`` otherwise.
        """
        return not self.get_descendant_count()

    def is_root_node(self):
        """
        Returns ``True`` if this model instance is a root node,
        ``False`` otherwise.
        """
        return self.level == 0

    @raise_if_unsaved
    def is_descendant_of(self, other, include_self=False):
        """
        Returns ``True`` if this model is a descendant of the given node,
        ``False`` otherwise.
        If include_self is True, also returns True if the two nodes are the same node.
        """

        if include_self and other.pk == self.pk:
            return True

        if self.tree_id != other.tree_id:
            return False
        else:
            return (
                (self.left > other.left) and
                (self.right < other.right)
            )

    @raise_if_unsaved
    def is_ancestor_of(self, other, include_self=False):
        """
        Returns ``True`` if this model is an ancestor of the given node,
        ``False`` otherwise.
        If include_self is True, also returns True if the two nodes are the same node.
        """
        if include_self and other.pk == self.pk:
            return True
        return other.is_descendant_of(self)

    def move_to(self, target, position='first-child'):
        """
        Convenience method for calling ``NestedIntervalManager.move_node`` with this
        model instance.
        """
        self._tree_manager.move_node(self, target, position)

    def _is_saved(self, using=None):
        if not self.pk or self.tree_id is None:
            return False
        return True

    @transaction.atomic
    def save(self, *args, **kwargs):

        if not kwargs.pop("nested_intervals_update_in_progress", False):
        
            if not self._is_saved():
                self.insert_at(self._new_parent or None, position='last-child')
            else:
                if self._new_parent is not False:
                    self._tree_manager._move_node(self, self._new_parent, position='last-child')

            # clear the _new_parent field now that it's saved
            self._new_parent = False

        # Only update nested_intervals fields if we're told to, or they have been changed.
        # This helps preserve tree integrity when saving on top of a modified tree.
        if not kwargs.get("update_fields", None) and not self._nested_intervals_fields_have_changed:
            kwargs["update_fields"] = self._get_user_field_names()
        
        # if all the nested_intervals fields are going to be saved, we can clear the "dirty bit"
        ni_fields = set(["left", "right", "level", "tree_id"])
        if kwargs.get("update_fields") is None or len(ni_fields - set(kwargs.get("update_fields") or [])) == 0:
            self._nested_intervals_fields_have_changed = False

        super(NestedIntervalsModel, self).save(*args, **kwargs)

    save.alters_data = True

    def delete(self, *args, **kwargs):
        """Calling ``delete`` on a node will delete it as well as its full
        subtree, as opposed to reattaching all the subnodes to its parent node.

        ``delete`` will not return anything. """
        self.get_descendants(include_self=True).delete()

    delete.alters_data = True

    def _get_user_field_names(self):
        """ Returns the list of user defined (i.e. non-nested_intervals internal) field names. """
        field_names = []
        internal_fields = ("left", "right", "tree_id", "level")
        for field in self._meta.fields:
            if (field.name not in internal_fields) and (not isinstance(field, AutoField)) and (not field.primary_key):
                field_names.append(field.name)
        return field_names
