from decimal import Decimal
from decimal import getcontext

from django.db.models.query import F

from .conf import DECIMAL_PLACES
from .exceptions import IntervalTooSmall

getcontext().prec = DECIMAL_PLACES


def get_range_conversion_f_expression_generator(old_left, old_right, new_left, new_right):
    old_size = old_right - old_left
    new_size = new_right - new_left

    def f_expression_generator(field):
        return (((F(field) - old_left) * new_size) / old_size) + new_left

    return f_expression_generator


def _calculate_sub_interval(outerleft, outerright, count):
    outerrange = outerright - outerleft
    increment = outerrange / (Decimal("2") * count + Decimal("1"))
    result = {
        "left": outerleft + increment,
        "right": outerright - increment,
        "increment": increment
    }
    if result["left"] == result["right"]:
        raise IntervalTooSmall("The interval has gotten too small! Oh noes!")
    return result


def get_interval_for_insertion_relative_to(target, position, count=1):
    if position not in ["first-child", "last-child", "left", "right"]:
        raise ValueError('An invalid position was given: %s.' % position)

    # if target is None, this is a root node, so use full range from 0 to 1
    if target is None:
        return {"left": Decimal("0"), "right": Decimal("1"), "increment": Decimal("1") / (Decimal("2") * count - Decimal("1"))}
    
    if not target._is_saved():
        raise ValueError("Can't insert relative to an unsaved node.")
    if position in ["left", "right"] and target.is_root_node():
        raise ValueError("Can't insert as a sibling of a root node.")

    if position == "first-child":
        # compute inserting to the left of the first child
        first_child = target.get_children().first()
        if first_child:
            return _calculate_sub_interval(target.left, first_child.left, count)
        else:
            return _calculate_sub_interval(target.left, target.right, count)
    elif position == "last-child":
        # compute inserting to the right of the last child
        last_child = target.get_children().last()
        if last_child:
            return _calculate_sub_interval(last_child.right, target.right, count)
        else:
            return _calculate_sub_interval(target.left, target.right, count)
    elif position == "left":
        # compute inserting to the left of the target
        previous = target.get_previous_sibling()
        if previous:
            return _calculate_sub_interval(previous.right, target.left, count)
        else:
            return _calculate_sub_interval(target.parent.left, target.left, count)
    elif position == "right":
        # compute inserting to the right of the target
        nxt = target.get_next_sibling()
        if nxt:
            return _calculate_sub_interval(target.right, nxt.left, count)
        else:
            return _calculate_sub_interval(target.right, target.parent.right, count)
