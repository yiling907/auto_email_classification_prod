"""
Unit-test directory conftest.
Each lambda test file imports its own 'lambda_function' module. This shared
name collides in Python's module cache when multiple files are collected in
the same pytest session. Each test file handles this by clearing the cache
before its own import (via sys.modules.pop). No additional hooks needed here.
"""
