def average(nums):
    """Return the arithmetic mean of nums."""
    total = 0
    count = 0
    for n in nums:
        total += n
        count += 1
    return total / count
