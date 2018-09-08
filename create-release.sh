#!/bin/bash -ex

python ./setup.py clean
rm -rf ./*.egg-info

python setup.py sdist bdist_wheel register upload
