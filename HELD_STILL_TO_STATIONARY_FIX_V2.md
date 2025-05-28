# Fix for HELD_STILL to STATIONARY Transition Issue

## Problem Description

The accelerometer was failing to transition from `HELD_STILL` to `STATIONARY` state when the device was placed on a stable surface. The logs showed that even though the sensor readings met the criteria for STATIONARY (very low linear acceleration and gyro values), the state remained stuck in `HELD_STILL`.

The key symptom was that the `stationary_candidate_readings` deque showed only "(1 readings)" instead of accumulating multiple readings needed for variance calculation.

## Root Cause

The issue was in the order of operations in `_determine_stable_state()`:

1. The code checked if readings met basic stationary criteria
2. Only then would it add readings to `stationary_candidate_readings` deque
3. But `_verify_stationary_consistency()` would clear the deque when starting fresh tracking
4. This created a situation where readings weren't properly accumulated when transitioning from HELD_STILL

Additionally, the condition for adding readings was:
```python
if meets_basic_stationary or self.stationary_candidate_start is not None:
    self.stationary_candidate_readings.append(linear_accel_mag)
```

This meant that if `stationary_candidate_start` was None (which it would be when first transitioning), the first reading that met criteria wouldn't be added.

## Solution

The fix involved two key changes:

### 1. In `_determine_stable_state()`:
- Moved the logic to add readings to the deque to happen immediately when basic stationary criteria are met
- Start tracking (`stationary_candidate_start`) at the same time as adding the first reading
- Don't clear the deque when starting tracking - we just added a reading!

```python
# Add readings to the deque BEFORE checking consistency
# This ensures we accumulate readings even when transitioning states
if meets_basic_stationary:
    self.stationary_candidate_readings.append(linear_accel_mag)
    # Start tracking if not already tracking
    if self.stationary_candidate_start is None:
        self.stationary_candidate_start = current_time
        # Don't clear readings here - we just added one!
        self.logger.debug(f"STATIONARY candidate tracking started from {current_state.name}")
```

### 2. In `_verify_stationary_consistency()`:
- Removed the logic that would reset tracking and clear the deque
- This function now assumes tracking has already been started by `_determine_stable_state()`
- Added a warning if called without tracking started (shouldn't happen)

## Testing

Use the provided `test_stationary_fix.py` script to verify the fix:

```bash
python test_stationary_fix.py
```

The test will show detailed information about state transitions and the accumulation of readings in the stationary candidate buffer. You should see:

1. Readings accumulate properly (2, 3, 4+ readings) when in HELD_STILL with low sensor values
2. Successful transition from HELD_STILL to STATIONARY after meeting consistency requirements
3. Proper variance calculation once enough readings are accumulated

## Expected Behavior After Fix

When placing the device on a stable surface from HELD_STILL state:
1. Readings immediately start accumulating in `stationary_candidate_readings`
2. After 4+ readings (consistency requirement), variance is calculated
3. If variance is low enough and duration requirement is met (0.8s), state transitions to STATIONARY
4. The transition should happen reliably without getting stuck in HELD_STILL 