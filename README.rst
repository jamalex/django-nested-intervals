========================================
django-nested-sets-with-rational-numbers
========================================

Utilities for implementing Nested Sets with Rational Numbers tree structures with your
Django Models and working with trees of Model instances.

Interface closely tracks Django MPTT. 

The tests have been extended to cover both sqlite and postgres (unlike mptt, which only covers sqlite).

I wouldn't recommend using it in SQLite for anything other than playing around, as SQLite doesn't have true fixed-point decimal types, it just uses floating point under the hood for DecimalField, so it can have unexpected rounding issues. Postgres, on the other hand, has true fixed-point decimals, and handles things well.

It's set up to detect if the intervals are getting too tight, and rebalance the tree by evenly spacing everything out again. It's currently using a naive recursive implementation for rebalancing (not super slow, but also not super fast).

Wouldn't recommend using this in production at the moment. If anyone wants to push it forward, happy for PRs or to shift ownership!
