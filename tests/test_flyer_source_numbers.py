"""flyer_reader.source_numbers: a thousands group split by a stray space
("$83, 315" in an HDC flyer) still grounds the joined number."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flyer_reader  # noqa: E402

nums = flyer_reader.source_numbers({"address": "1 Main St"}, "1 Person $83, 315 -$95,040")
assert 83315.0 in nums and 95040.0 in nums, nums
assert 83.0 in nums and 315.0 in nums          # the raw parts stay
print("ok flyer source numbers")
