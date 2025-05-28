# Fix for HELD_STILL to STATIONARY Transition Issue

## Problem Description

The device was unable to transition from `HELD_STILL` state to `STATIONARY` state. When the user held the device still and then placed it on a table, instead of transitioning to `STATIONARY`, the system would either:
1. Stay in `HELD_STILL` state indefinitely, or
2. Incorrectly transition from `STATIONARY` to `HELD_STILL` after 8 seconds

## Root Causes Identified

1. **Stale readings in the variance buffer**: The `stationary_candidate_readings` deque was not being cleared when the stationary candidate tracking was reset. This meant old readings from the `HELD_STILL` state were contaminating the variance calculation.

2. **Overly strict variance threshold**: The maximum allowed variance of 0.050 was too strict for real hardware. Even when trying to hold the device perfectly still, readings would vary from 0.084 to 0.171 m/s², resulting in a variance that exceeded the threshold.

3. **Too short variance timeout**: The 8-second timeout for variance checking was too aggressive, causing valid STATIONARY states to be rejected prematurely.

## Solutions Implemented

### 1. Clear the readings buffer when resetting tracking

Added `self.stationary_candidate_readings.clear()` in three places:
- When starting new stationary candidate tracking
- When resetting due to failing basic criteria
- When rejecting due to high variance

```python
# In _verify_stationary_consistency
if self.stationary_candidate_start is None:
    self.stationary_candidate_start = current_time
    # Clear old readings when starting fresh stationary candidate tracking
    # This is especially important when transitioning from HELD_STILL
    self.stationary_candidate_readings.clear()
    return False
```

### 2. Increased variance threshold

Changed from 0.050 to 0.100 to accommodate real hardware variance:

```python
self.stationary_max_variance = 0.100  # m/s² - More realistic for actual hardware variance (was 0.050)
```

### 3. Made variance timeout configurable and increased it

Added a configurable timeout and increased from 8.0 to 15.0 seconds:

```python
self.stationary_variance_timeout = 15.0  # seconds - Much longer patience for variance (was hardcoded 8.0)
```

## Expected Behavior After Fix

1. **Holding device still**: Should detect `HELD_STILL` state (or possibly `STATIONARY` if very still)
2. **Placing on table**: Should transition to `STATIONARY` within 0.8-2.0 seconds
3. **Stable on table**: Should remain in `STATIONARY` state without oscillation
4. **Picking up from table**: Should transition to `HELD_STILL` or `MOVING`

## Testing

Use the provided test scripts:
- `test_held_still_to_stationary.py` - Basic test showing state transitions
- `test_held_still_to_stationary_debug.py` - Debug version showing variance calculations

## Technical Details

The variance calculation uses the last 4 readings (configurable via `stationary_consistency_required`) to determine if the device is truly stationary. The variance must be below the threshold for the minimum duration (0.8s) to confirm STATIONARY state.

The fix ensures that:
1. Old readings don't contaminate new state detection attempts
2. Natural hardware variance is accommodated
3. The system has enough time to stabilize before rejecting based on variance 