"""
A settings module for running tests using a postgres db backend.
"""
from __future__ import absolute_import, print_function, unicode_literals

from .settings import *  # noqa

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'USER': 'postgres',
        'PASSWORD': '',
        'NAME': 'postgres',  # This module should never be used outside of tests -- so this name is irrelevant
        'TEST': {
            'NAME': 'travis_ci_default'
        }
    },
}
