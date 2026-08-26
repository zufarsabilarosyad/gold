"""The test suite for strongback.

Every test here goes through a public interface.  Nothing imports a private
helper or asserts on a repr, because the point of the suite is to pin the
*behaviour* the conventions produce -- if an internal changes shape and the
numbers stay right, no test should notice.
"""
