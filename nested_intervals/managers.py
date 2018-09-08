"""
A custom manager for working with trees of objects.
"""
from __future__ import unicode_literals
import functools
import uuid

from django.db import models, connections, router, transaction
from django.db.models import F

from decimal import Decimal

from .exceptions import InvalidMove, IntervalTooSmall
from .querysets import NestedIntervalsQuerySet

from .intervals import get_interval_for_insertion_relative_to, get_range_conversion_f_expression_generator


class NestedIntervalsManager(models.Manager.from_queryset(NestedIntervalsQuerySet)):
    """
    A manager for working with trees of Nested Interval objects.
    """

    def get_queryset(self, *args, **kwargs):
        """
        Ensures that this manager always returns nodes in tree order.
        """
        return super(NestedIntervalsManager, self).get_queryset(*args, **kwargs).order_by("tree_id", "left")

    def get_queryset_descendants(self, queryset, include_self=False):
        """
        Returns a queryset containing the descendants of all nodes in the
        given queryset.

        If ``include_self=True``, nodes in ``queryset`` will also
        be included in the result.
        """
        qs = queryset.none()
        for node in queryset.all():
            qs = qs | node.get_descendants(include_self=include_self)
        return qs.distinct()

    def get_queryset_ancestors(self, queryset, include_self=False):
        """
        Returns a queryset containing the ancestors
        of all nodes in the given queryset.

        If ``include_self=True``, nodes in ``queryset`` will also
        be included in the result.
        """
        qs = queryset.none()
        for node in queryset.all():
            qs = qs | node.get_ancestors(include_self=include_self)
        return qs.distinct()

    def _get_connection(self, **hints):
        return connections[router.db_for_write(self.model, **hints)]

    @transaction.atomic
    def insert_node(self, node, target, position='last-child', save=False):
        """
        Sets up the tree state for ``node`` (which has not yet been
        inserted into in the database) so it will be positioned relative
        to a given ``target`` node as specified by ``position``.

        A ``target`` of ``None`` indicates that ``node`` should be inserted
        as the root node of a new tree.

        If ``save`` is ``True``, ``node``'s ``save()`` method will be
        called before it is returned.
        """        

        if node._is_saved():
            raise ValueError('Cannot insert a node which has already been saved.')

        # it's a new node, and hence doesn't have any kids, so we can just set the node's fields
        if target is None:
            # if it has no target, we just make a new singleton tree
            node.level = 0
            node.left = Decimal("0")
            node.right = Decimal("1")
            node.tree_id = uuid.uuid4()
        else:
            # if it has a target, insert it into the appropriate place relative to the target
            interval = self.get_interval_for_insertion_relative_to_with_rebalance(target, position=position)
            node.left, node.right = interval["left"], interval["right"]
            if "child" in position:
                node.level = target.level + 1
            else:
                node.level = target.level
            node.tree_id = target.tree_id

        node._nested_intervals_fields_have_changed = True

        if save:
            node.save(nested_intervals_update_in_progress=True)
        return node

    def get_interval_for_insertion_relative_to_with_rebalance(self, target, position, count=1):
        try:
            interval = get_interval_for_insertion_relative_to(target, position=position, count=count)
        except IntervalTooSmall:
            # if needed due to the intervals getting too tight, rebalance the tree to make room
            self.rebalance_tree(target.tree_id)
            target.refresh_from_db()
            interval = get_interval_for_insertion_relative_to(target, position=position)
        return interval

    @transaction.atomic
    def move_node(self, node, target, position='last-child'):
        """
        Moves ``node`` relative to a given ``target`` node as specified
        by ``position``.

        A ``target`` of ``None`` indicates that ``node`` should be
        turned into a root node.

        Valid values for ``position`` are ``'first-child'``,
        ``'last-child'``, ``'left'`` or ``'right'``.

        ``node`` and its children will be modified to reflect their new
        tree state in the database.
        """
        self._move_node(node, target, position)
        node.save(nested_intervals_update_in_progress=True)

    def _move_node(self, node, target, position='last-child'):

        # first check that we're not making any circular loops
        if position in ["last-child", "first-child"]:
            if node == target:
                raise InvalidMove('A node may not be made a child of itself.')
            if target and node.is_ancestor_of(target):
                raise InvalidMove("A node may not be made a child of any of its descendants.")
        elif position in ["left", "right"]:
            if node == target:
                raise InvalidMove('A node may not be made a sibling of itself.')
            elif target and node.is_ancestor_of(target):
                raise InvalidMove('A node may not be made a sibling of any of its descendants.')

        # first, calculate what we're going to need to change
        descendant_count = node.get_descendant_count()
        interval = self.get_interval_for_insertion_relative_to_with_rebalance(target, position=position, count=descendant_count+1)
        converter = get_range_conversion_f_expression_generator(node.left, node.right, interval["left"], interval["right"])
        new_tree_id = None
        if target is None:
            level_offset = -node.level
            new_tree_id = uuid.uuid4()
        else:
            if position in ["left", "right"]:
                level_offset = target.level - node.level
            else:
                level_offset = target.level + 1 - node.level
            new_tree_id = target.tree_id if target.tree_id != node.tree_id else None
                                    
        # if there are descendants, update their values first
        if descendant_count:
            updates = {
                "left": converter("left"),
                "right": converter("right"),
            }
            if new_tree_id:
                updates["tree_id"] = new_tree_id
            if level_offset:
                updates["level"] = F("level") + level_offset
            node.get_descendants().update(**updates)

        # update the current node itself
        node.left, node.right = interval["left"], interval["right"]
        node.level += level_offset
        if new_tree_id:
            node.tree_id = new_tree_id

        node._nested_intervals_fields_have_changed = True

    def root_node(self, tree_id):
        """
        Returns the root node of the tree with the given id.
        """
        return self.filter(tree_id=tree_id, level=0).get()

    def root_nodes(self):
        """
        Creates a ``QuerySet`` containing root nodes.
        """
        return self.filter(level=0)

    def rebalance_all_trees(self):
        """
        Rebalances all trees in the database table to have evenly spaced intervals.
        """

        tree_ids = self.root_nodes().values_list('tree_id', flat=True)

        for tree_id in tree_ids:
            self.rebalance_tree(tree_id)

    @transaction.atomic
    def rebalance_tree(self, tree_id):
        """
        Rebalances the tree with given ``tree_id`` in database table to have evenly spaced intervals.
        """

        root = self.root_node(tree_id)
        nodes = root.get_descendants(include_self=True)
        interval = get_interval_for_insertion_relative_to(None, "last-child", count=nodes.count())
        self._rebalance_helper(root, interval["left"], interval["increment"])

    def _rebalance_helper(self, node, left, increment):
        
        # if there are no children, the right value is the left value plus the increment
        right = left + increment
        
        # recurse down into the children to update them
        for child in node.get_children():
            right = self._rebalance_helper(child, right, increment)

        # update the left and right values for this node
        self.filter(pk=node.pk).update(
            left=left,
            right=right,
        )

        return right + increment


# TODO: when inserting nodes and their descendants, we're just scaling their left/right values, which might lead to "too small" intervals
# We should either just always re-assign evenly based on a range (i.e. rebalance the subtree being inserted), or check its current min interval first.