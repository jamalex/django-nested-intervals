# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import io
import mock
import os
import re
import string
import sys
import tempfile
import unittest


from django.contrib.auth.models import Group, User
from django.db.models import Q
from django.db.models.query_utils import DeferredAttribute
from django.apps import apps
from django.template import Template, TemplateSyntaxError, Context
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils.six import string_types, PY3, b, assertRaisesRegex
from django.contrib.admin.views.main import ChangeList
from django.contrib.admin import ModelAdmin, site

from nested_intervals.exceptions import InvalidMove
from nested_intervals.models import NestedIntervalsModel
from nested_intervals.managers import NestedIntervalsManager

from myapp.models import (
    Category, Item, Genre, CustomPKName, SingleProxyModel, DoubleProxyModel,
    ConcreteModel, AutoNowDateFieldModel, Person,
    CustomTreeQueryset, CustomNestedIntervalsManager, Book, UUIDNode, Student,
    MultipleManagerModel)

def print_tree(node, indent=0):
    print("{indent}{name} ({left}, {right})".format(indent="\t"*indent, name=getattr(node, "name", node.id), left=node.left, right=node.right))
    for child in node.get_children():
        print_tree(child, indent+1)


def get_tree_details(nodes):
    """
    Creates pertinent tree details for the given list of nodes.
    The fields are:
        id  parent_id  tree_id  level  left  right
    """
    if hasattr(nodes, 'order_by'):
        nodes = list(nodes.order_by('tree_id', 'left', 'pk'))
    nodes = list(nodes)
    return '\n'.join(['%s %s %s' %
                      (n.pk, n.parent.id if n.parent else "-", n.level) for n in nodes])


leading_whitespace_re = re.compile(r'^\s+', re.MULTILINE)


def tree_details(text):
    """
    Trims leading whitespace from the given text specifying tree details
    so triple-quoted strings can be used to provide tree details in a
    readable format (says who?), to be compared with the result of using
    the ``get_tree_details`` function.
    """
    return leading_whitespace_re.sub('', text.rstrip())


class TreeTestCase(TransactionTestCase):

    def assertTreeEqual(self, tree1, tree2):
        if not isinstance(tree1, string_types):
            tree1 = get_tree_details(tree1)
        tree1 = tree_details(tree1)
        if not isinstance(tree2, string_types):
            tree2 = get_tree_details(tree2)
        tree2 = tree_details(tree2)
        return self.assertEqual(tree1, tree2, "\n%r\n != \n%r" % (tree1, tree2))


class DocTestTestCase(TreeTestCase):

    @mock.patch("uuid.uuid4")
    def test_run_doctest(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[:16]])
        class DummyStream:
            content = ""
            encoding = 'utf8'

            def write(self, text):
                self.content += text

            def flush(self):
                pass

        dummy_stream = DummyStream()
        before = sys.stdout
        sys.stdout = dummy_stream


        with open(os.path.join(os.path.dirname(__file__), 'doctests.txt')) as f:
            with tempfile.NamedTemporaryFile() as temp:
                text = f.read()

                if PY3:
                    # unicode literals in the doctests screw up doctest on py3.
                    # this is pretty icky, but I can't find any other
                    # workarounds :(
                    text = re.sub(r"""\bu(["\'])""", r"\1", text)
                    temp.write(b(text))
                else:
                    temp.write(text)

                temp.flush()

                import doctest
                doctest.testfile(
                    temp.name,
                    module_relative=False,
                    optionflags=doctest.IGNORE_EXCEPTION_DETAIL | doctest.ELLIPSIS,
                    encoding='utf-8',
                )
                sys.stdout = before
                content = dummy_stream.content
                if content:
                    before.write(content + '\n')
                    self.fail()

# genres.json defines the following tree structure
#
# 1 - 1 0 1 16   action
# 2 1 1 1 2 9    +-- platformer
# 3 2 1 2 3 4    |   |-- platformer_2d
# 4 2 1 2 5 6    |   |-- platformer_3d
# 5 2 1 2 7 8    |   +-- platformer_4d
# 6 1 1 1 10 15  +-- shmup
# 7 6 1 2 11 12      |-- shmup_vertical
# 8 6 1 2 13 14      +-- shmup_horizontal
# 9 - 2 0 1 6    rpg
# 10 9 2 1 2 3   |-- arpg
# 11 9 2 1 4 5   +-- trpg

@mock.patch("uuid.uuid4")
class ReparentingTestCase(TreeTestCase):

    """
    Test that trees are in the appropriate state after reparenting and
    that reparented items have the correct tree attributes defined,
    should they be required for use after a save.
    """
    fixtures = ['genres.json']

    def test_new_root_from_subtree(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        
        shmup = Genre.objects.get(id=6)
        shmup.parent = None
        shmup.save()
        self.assertTreeEqual([shmup], '6 - 0')
        self.assertTreeEqual(Genre.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 2 2
            9 - 0
            10 9 1
            11 9 1
            6 - 0
            7 6 1
            8 6 1
        """)

    def test_new_root_from_leaf_with_siblings(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        platformer_2d = Genre.objects.get(id=3)
        platformer_2d.parent = None
        platformer_2d.save()
        self.assertTreeEqual([platformer_2d], '3 - 0')
        self.assertTreeEqual(Genre.objects.all(), """
            1 - 0
            2 1 1
            4 2 2
            5 2 2
            6 1 1
            7 6 2
            8 6 2
            9 - 0
            10 9 1
            11 9 1
            3 - 0
        """)

    def test_new_child_from_root(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        action = Genre.objects.get(id=1)
        rpg = Genre.objects.get(id=9)
        action.parent = rpg
        action.save()
        self.assertTreeEqual([action], '1 9 1')
        self.assertTreeEqual([rpg], '9 - 0')
        self.assertTreeEqual(Genre.objects.all(), """
            9 - 0
            10 9 1
            11 9 1
            1 9 1
            2 1 2
            3 2 3
            4 2 3
            5 2 3
            6 1 2
            7 6 3
            8 6 3
        """)

    def test_move_leaf_to_other_tree(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        shmup_horizontal = Genre.objects.get(id=8)
        rpg = Genre.objects.get(id=9)
        shmup_horizontal.parent = rpg
        shmup_horizontal.save()
        self.assertTreeEqual([shmup_horizontal], '8 9 1')
        self.assertTreeEqual([rpg], '9 - 0')
        self.assertTreeEqual(Genre.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 2 2
            6 1 1
            7 6 2
            9 - 0
            10 9 1
            11 9 1
            8 9 1
        """)

    def test_move_subtree_to_other_tree(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        shmup = Genre.objects.get(id=6)
        trpg = Genre.objects.get(id=11)
        shmup.parent = trpg
        shmup.save()
        self.assertTreeEqual([shmup], '6 11 2')
        self.assertTreeEqual([trpg], '11 9 1')
        self.assertTreeEqual(Genre.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 2 2
            9 - 0
            10 9 1
            11 9 1
            6 11 2
            7 6 3
            8 6 3
        """)

    def test_move_child_up_level(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        shmup_horizontal = Genre.objects.get(id=8)
        action = Genre.objects.get(id=1)
        shmup_horizontal.parent = action
        shmup_horizontal.save()
        self.assertTreeEqual([shmup_horizontal], '8 1 1')
        self.assertTreeEqual([action], '1 - 0')
        self.assertTreeEqual(Genre.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 2 2
            6 1 1
            7 6 2
            8 1 1
            9 - 0
            10 9 1
            11 9 1
        """)

    def test_move_subtree_down_level(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        shmup = Genre.objects.get(id=6)
        platformer = Genre.objects.get(id=2)
        shmup.parent = platformer
        shmup.save()
        self.assertTreeEqual([shmup], '6 2 2')
        self.assertTreeEqual([platformer], '2 1 1')
        self.assertTreeEqual(Genre.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 2 2
            6 2 2
            7 6 3
            8 6 3
            9 - 0
            10 9 1
            11 9 1
        """)

    def test_move_to(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        rpg = Genre.objects.get(pk=9)
        action = Genre.objects.get(pk=1)
        rpg.move_to(action)
        rpg.save()
        self.assertEqual(rpg.parent, action)

    def test_invalid_moves(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[3:16]])
        # A node may not be made a child of itself
        action = Genre.objects.get(id=1)
        action.parent = action
        platformer = Genre.objects.get(id=2)
        platformer.parent = platformer
        self.assertRaises(InvalidMove, action.save)
        self.assertRaises(InvalidMove, platformer.save)

        # A node may not be made a child of any of its descendants
        platformer_4d = Genre.objects.get(id=5)
        action.parent = platformer_4d
        platformer.parent = platformer_4d
        self.assertRaises(InvalidMove, action.save)
        self.assertRaises(InvalidMove, platformer.save)

        # New parent is still set when an error occurs
        self.assertEqual(action.parent, platformer_4d)
        self.assertEqual(platformer.parent, platformer_4d)


class ConcurrencyTestCase(TreeTestCase):

    """
    Test that tree structure remains intact when saving nodes (without setting new parent) after
    tree structure has been changed.
    """
    @mock.patch("uuid.uuid4")
    def setUp(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[:16]])

        fruit = ConcreteModel.objects.create(name="Fruit")
        veggie = ConcreteModel.objects.create(name="Veggie")
        ConcreteModel.objects.create(name="Apple", parent=fruit)
        ConcreteModel.objects.create(name="Pear", parent=fruit)
        ConcreteModel.objects.create(name="Tomato", parent=veggie)
        ConcreteModel.objects.create(name="Carrot", parent=veggie)
        self.lowest_id = fruit.id

    def _assert_original_tree_state(self):
        # sanity check
        
        self.assertTreeEqual(ConcreteModel.objects.all(), """
            {0} - 0
            {2} {0} 1
            {3} {0} 1
            {1} - 0
            {4} {1} 1
            {5} {1} 1
        """.format(*range(self.lowest_id, self.lowest_id+8)))

    def _modify_tree(self):
        fruit = ConcreteModel.objects.get(name="Fruit")
        veggie = ConcreteModel.objects.get(name="Veggie")
        veggie.move_to(fruit)

    def _assert_modified_tree_state(self):
        carrot = ConcreteModel.objects.get(id=self.lowest_id+5)
        self.assertTreeEqual([carrot], '{5} {1} 2'.format(*range(self.lowest_id, self.lowest_id+8)))
        self.assertTreeEqual(ConcreteModel.objects.all(), """
            {0} - 0
            {1} {0} 1
            {4} {1} 2
            {5} {1} 2
            {2} {0} 1
            {3} {0} 1
        """.format(*range(self.lowest_id, self.lowest_id+8)))

    def test_node_save_after_tree_restructuring(self):

        self._assert_original_tree_state()

        carrot = ConcreteModel.objects.get(id=self.lowest_id+5)

        self._modify_tree()

        carrot.name = "Purple carrot"
        carrot.save()

        self._assert_modified_tree_state()

    def test_node_save_after_tree_restructuring_with_update_fields(self):
        """
        Test that model is saved properly when passing update_fields
        """

        self._assert_original_tree_state()

        carrot = ConcreteModel.objects.get(id=self.lowest_id+5)

        self._modify_tree()

        # update with kwargs
        carrot.name = "Won't change"
        carrot.ghosts = "Will get updated"
        carrot.save(update_fields=["ghosts"])

        self._assert_modified_tree_state()

        updated_carrot = ConcreteModel.objects.get(id=self.lowest_id+5)

        self.assertEqual(updated_carrot.ghosts, carrot.ghosts)
        self.assertNotEqual(updated_carrot.name, carrot.name)


# categories.json defines the following tree structure:
#
# 1 - 1 0 1 20    games
# 2 1 1 1 2 7     +-- wii
# 3 2 1 2 3 4     |   |-- wii_games
# 4 2 1 2 5 6     |   +-- wii_hardware
# 5 1 1 1 8 13    +-- xbox360
# 6 5 1 2 9 10    |   |-- xbox360_games
# 7 5 1 2 11 12   |   +-- xbox360_hardware
# 8 1 1 1 14 19   +-- ps3
# 9 8 1 2 15 16       |-- ps3_games
# 10 8 1 2 17 18      +-- ps3_hardware

@mock.patch("uuid.uuid4")
class DeletionTestCase(TreeTestCase):

    """
    Tests that the tree structure is maintained appropriately in various
    deletion scenarios.
    """
    fixtures = ['categories.json']

    def test_delete_root_node(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[2:16]])
        # Add a few other roots to verify that they aren't affected
        Category(name='Another root').save()
        Category(name='Yet another root').save()
        self.assertTreeEqual(Category.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 1 1
            6 5 2
            7 5 2
            8 1 1
            9 8 2
            10 8 2
            11 - 0
            12 - 0
        """)

        Category.objects.get(id=1).delete()
        self.assertTreeEqual(
            Category.objects.all(), """
            11 - 0
            12 - 0
        """)

    def test_delete_last_node_with_siblings(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[2:16]])
        Category.objects.get(id=9).delete()
        self.assertTreeEqual(Category.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 1 1
            6 5 2
            7 5 2
            8 1 1
            10 8 2
        """)

    def test_delete_last_node_with_descendants(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[2:16]])
        Category.objects.get(id=8).delete()
        self.assertTreeEqual(Category.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 1 1
            6 5 2
            7 5 2
        """)

    def test_delete_node_with_siblings(self, uuid4_mock):
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[2:16]])
        child = Category.objects.get(id=6)
        parent = child.parent
        self.assertEqual(parent.get_descendant_count(), 2)
        child.delete()
        self.assertTreeEqual(Category.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            5 1 1
            7 5 2
            8 1 1
            9 8 2
            10 8 2
        """)
        self.assertEqual(parent.get_descendant_count(), 1)
        parent = Category.objects.get(pk=parent.pk)
        self.assertEqual(parent.get_descendant_count(), 1)

    def test_delete_node_with_descendants_and_siblings(self, uuid4_mock):
        """
        Regression test for Issue 23 - we used to use pre_delete, which
        resulted in tree cleanup being performed for every node being
        deleted, rather than just the node on which ``delete()`` was
        called.
        """
        uuid4_mock.side_effect = iter([char * 32 for char in string.hexdigits[2:16]])
        Category.objects.get(id=5).delete()
        self.assertTreeEqual(Category.objects.all(), """
            1 - 0
            2 1 1
            3 2 2
            4 2 2
            8 1 1
            9 8 2
            10 8 2
        """)


class IntraTreeMovementTestCase(TreeTestCase):
    pass


class InterTreeMovementTestCase(TreeTestCase):
    pass


class PositionedInsertionTestCase(TreeTestCase):
    pass


class CustomPKNameTestCase(TreeTestCase):

    def setUp(self):
        manager = CustomPKName.objects
        c1 = manager.create(name="c1")
        manager.create(name="c11", parent=c1)
        manager.create(name="c12", parent=c1)

        c2 = manager.create(name="c2")
        manager.create(name="c21", parent=c2)
        manager.create(name="c22", parent=c2)

        manager.create(name="c3")

    def test_get_next_sibling(self):
        root = CustomPKName.objects.get(name="c12")
        sib = root.get_next_sibling()
        self.assertTrue(sib is None)


class ManagerTests(TreeTestCase):
    fixtures = ['categories.json',
                'genres.json',
                'persons.json']

    def test_all_managers_have_correct_model(self):
        # all tree managers should have the correct model.
        for model in apps.get_models():
            if not issubclass(model, NestedIntervalsModel):
                continue
            self.assertEqual(model()._tree_manager.model, model)

    def test_get_queryset_descendants(self):
        def get_desc_names(qs, include_self=False):
            desc = qs.model.objects.get_queryset_descendants(
                qs, include_self=include_self)
            return [node.name for node in desc.order_by('name')]

        qs = Category.objects.filter(Q(name='Nintendo Wii') | Q(name='PlayStation 3'))

        self.assertEqual(
            get_desc_names(qs),
            ['Games', 'Games',
             'Hardware & Accessories', 'Hardware & Accessories'],
        )

        self.assertEqual(
            get_desc_names(qs, include_self=True),
            ['Games', 'Games', 'Hardware & Accessories',
             'Hardware & Accessories', 'Nintendo Wii', 'PlayStation 3']
        )

        qs = Genre.objects.filter(level=0)

        self.assertEqual(
            get_desc_names(qs),
            ['2D Platformer', '3D Platformer', '4D Platformer',
             'Action RPG', 'Horizontal Scrolling Shootemup', 'Platformer',
             'Shootemup', 'Tactical RPG', 'Vertical Scrolling Shootemup']
        )

        self.assertEqual(
            get_desc_names(qs, include_self=True),
            ['2D Platformer', '3D Platformer', '4D Platformer',
             'Action', 'Action RPG', 'Horizontal Scrolling Shootemup',
             'Platformer', 'Role-playing Game', 'Shootemup', 'Tactical RPG',
             'Vertical Scrolling Shootemup']
        )

    def _get_anc_names(self, qs, include_self=False):
        anc = qs.model.objects.get_queryset_ancestors(
            qs, include_self=include_self)
        return [node.name for node in anc.order_by('name')]

    def test_get_queryset_ancestors(self):
        qs = Category.objects.filter(Q(name='Nintendo Wii') | Q(name='PlayStation 3'))

        self.assertEqual(
            self._get_anc_names(qs),
            ['PC & Video Games']
        )

        self.assertEqual(
            self._get_anc_names(qs, include_self=True),
            ['Nintendo Wii', 'PC & Video Games', 'PlayStation 3']
        )

        qs = Genre.objects.filter(level=0)
        self.assertEqual(self._get_anc_names(qs), [])
        self.assertEqual(
            self._get_anc_names(qs, include_self=True),
            ['Action', 'Role-playing Game'])

    def test_get_all_queryset_ancestors(self):
        qs = Genre.objects.all()
        self.assertEqual(
            self._get_anc_names(qs, include_self=True),
            list(Genre.objects.values_list('name', flat=True).order_by('name')))

    def test_custom_querysets(self):
        """
        Test that a custom manager also provides custom querysets.
        """

        self.assertTrue(isinstance(Person.objects.all(), CustomTreeQueryset))
        self.assertTrue(isinstance(Person.objects.all()[0].get_children(), CustomTreeQueryset))
        self.assertTrue(hasattr(Person.objects.none(), 'custom_method'))

        # Check that empty querysets get custom methods
        self.assertTrue(hasattr(Person.objects.all()[0].get_children().none(), 'custom_method'))

        self.assertEqual(
            type(Person.objects.all()),
            type(Person.objects.root_nodes())
        )

    def test_manager_from_custom_queryset(self):
        """
        Test that a manager created from a custom queryset works.
        Regression test for #378.
        """
        NestedIntervalsManager.from_queryset(CustomTreeQueryset)().contribute_to_class(Genre, 'my_manager')

        self.assertIsInstance(Genre.my_manager.get_queryset(), CustomTreeQueryset)

    def test_num_queries_on_get_queryset_descendants(self):
        """
        Test the number of queries to access descendants
        is not O(n).
        At the moment it is O(1)+1.
        Ideally we should aim for O(1).
        """
        with self.assertNumQueries(2):
            qs = Category.objects.get_queryset_descendants(
                Category.objects.all(), include_self=True)
            self.assertEqual(len(qs), 10)

    def test_default_manager_with_multiple_managers(self):
        """
        Test that a model with multiple managers defined always uses the
        default manager as the tree manager.
        """
        self.assertEqual(type(MultipleManagerModel()._tree_manager), NestedIntervalsManager)


class TestAutoNowDateFieldModel(TreeTestCase):

    def test_save_auto_now_date_field_model(self):
        a = AutoNowDateFieldModel()
        a.save()


class TestUnsaved(TreeTestCase):

    def test_unsaved(self):
        for method in [
            'get_ancestors',
            'get_family',
            'get_children',
            'get_descendants',
            'get_leafnodes',
            'get_next_sibling',
            'get_previous_sibling',
            'get_root',
            'get_siblings',
        ]:
            assertRaisesRegex(
                self,
                ValueError,
                'Cannot call %s on unsaved Genre instances' % method,
                getattr(Genre(), method))


class QuerySetTests(TreeTestCase):
    fixtures = ['categories.json']

    def test_get_ancestors(self):
        self.assertEqual(
            [
                c.pk for c in
                Category.objects.get(name="Nintendo Wii").get_ancestors(include_self=False)],
            [
                c.pk for c in
                Category.objects.filter(name="Nintendo Wii").get_ancestors(include_self=False)],
        )
        self.assertEqual(
            [
                c.pk for c in
                Category.objects.get(name="Nintendo Wii").get_ancestors(include_self=True)],
            [
                c.pk for c in
                Category.objects.filter(name="Nintendo Wii").get_ancestors(include_self=True)],
        )

    def test_get_descendants(self):
        self.assertEqual(
            [
                c.pk for c in
                Category.objects.get(name="Nintendo Wii").get_descendants(include_self=False)],
            [
                c.pk for c in
                Category.objects.filter(name="Nintendo Wii").get_descendants(include_self=False)],
        )
        self.assertEqual(
            [
                c.pk for c in
                Category.objects.get(name="Nintendo Wii").get_descendants(include_self=True)],
            [
                c.pk for c in
                Category.objects.filter(name="Nintendo Wii").get_descendants(include_self=True)],
        )


class UUIDPrimaryKey(TreeTestCase):

    def test_save_uuid_model(self):
        n1 = UUIDNode.objects.create(name='node')
        n2 = UUIDNode.objects.create(name='sub_node', parent=n1)
        self.assertEqual(n1.name, 'node')
        self.assertEqual(n1.tree_id, n2.tree_id)
        self.assertEqual(n2.parent, n1)

    def test_move_uuid_node(self):
        n1 = UUIDNode.objects.create(name='n1')
        n2 = UUIDNode.objects.create(name='n2', parent=n1)
        n3 = UUIDNode.objects.create(name='n3', parent=n1)
        self.assertEqual(list(n1.get_children()), [n2, n3])

        n3.move_to(n2, 'left')

        self.assertEqual(list(n1.get_children()), [n3, n2])

    def test_move_root_node(self):
        root1 = UUIDNode.objects.create(name='n1')
        child = UUIDNode.objects.create(name='n2', parent=root1)
        root2 = UUIDNode.objects.create(name='n3')
        self.assertEqual(list(root1.get_children()), [child])

        root2.move_to(child, 'left')

        self.assertEqual(list(root1.get_children()), [root2, child])

    def test_move_child_node(self):
        root1 = UUIDNode.objects.create(name='n1')
        child1 = UUIDNode.objects.create(name='n2', parent=root1)
        root2 = UUIDNode.objects.create(name='n3')
        child2 = UUIDNode.objects.create(name='n4', parent=root2)
        self.assertEqual(list(root1.get_children()), [child1])

        child2.move_to(child1, 'left')

        self.assertEqual(list(root1.get_children()), [child2, child1])


class DirectParentAssignment(TreeTestCase):
    def test_assignment(self):
        n1 = Category.objects.create()
        n2 = Category.objects.create()
        n1.parent_id = n2.id
        n1.save()
