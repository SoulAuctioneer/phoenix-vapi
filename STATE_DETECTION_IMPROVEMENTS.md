# State Detection Improvements - Fix for STATIONARY/HELD_STILL Oscillation

## Problem Identified

The system was oscillating between `STATIONARY` and `HELD_STILL` states when holding the device steady by hand, as shown in the logs:

```
DEBUG - State change: HELD_STILL → STATIONARY
DEBUG - State change: STATIONARY → HELD_STILL
DEBUG - State change: HELD_STILL → STATIONARY
```

**Root Cause**: The linear acceleration values when holding by hand (0.23-0.82 m/s²) were right at the boundary between the two states, causing rapid transitions due to natural hand tremor.

## Solutions Implemented

### 1. ✅ Improved Hysteresis Logic

**Before**: Simple hysteresis that only applied higher thresholds when *currently* in a stable state.

**After**: Bidirectional hysteresis that works differently based on transition direction:

- **Exiting a stable state**: Requires higher thresholds (harder to leave)
- **Entering a stable state**: Uses normal thresholds (easier to enter)
- **Between stable states**: Uses special logic to prevent ping-ponging

```python
# Example: Currently STATIONARY
stationary_exit_threshold = base_threshold * 2.5  # Harder to exit
held_still_entry_threshold = base_threshold       # Normal entry

# Example: Currently HELD_STILL  
held_still_exit_threshold = base_threshold * 2.5  # Harder to exit
stationary_entry_threshold = base_threshold * 0.8 # More restrictive entry
```

### 2. ✅ Adjusted Thresholds Based on Real Data

**Before** (too permissive for STATIONARY):
- STATIONARY: Linear < 0.25 m/s²
- HELD_STILL: Linear < 0.80 m/s²

**After** (based on observed hand-held values of 0.23-0.82 m/s²):
- STATIONARY: Linear < 0.15 m/s² (more restrictive - truly still)
- HELD_STILL: Linear < 1.0 m/s² (more permissive - accommodates hand tremor)

### 3. ✅ Enhanced Debug Logging

Added detailed logging to understand state transitions:

```python
self.logger.debug(f"State transition candidate: {current_state.name} → {candidate_state.name}")
self.logger.debug(f"  Linear: {linear_accel_mag:.3f} (STAT<{stationary_threshold:.3f}, HELD<{held_still_threshold:.3f})")
```

### 4. ✅ Reduced Hysteresis Factor

**Before**: 3.0x (too aggressive, made transitions sluggish)
**After**: 2.5x (still prevents oscillation but more responsive)

## Expected Behavior After Fix

### When Holding Device Steady by Hand:
- **Initial**: UNKNOWN → MOVING (brief motion during pickup)
- **Settle**: MOVING → HELD_STILL (recognizes hand-held state)
- **Stable**: Stays in HELD_STILL (no more oscillation)

### When Placing on Table:
- **Transition**: HELD_STILL → STATIONARY (when truly motionless)
- **Stable**: Stays in STATIONARY (very low thresholds)

### When Picking Up from Table:
- **Transition**: STATIONARY → HELD_STILL or MOVING (depending on motion level)
- **Hysteresis**: Requires clear motion to exit STATIONARY (prevents false triggers)

## Technical Details

### Threshold Matrix

| Current State | STATIONARY Threshold | HELD_STILL Threshold | Logic |
|---------------|---------------------|---------------------|-------|
| STATIONARY | 0.15 × 2.5 = 0.375 | 1.0 (normal) | Hard to exit, easy to transition to HELD_STILL |
| HELD_STILL | 0.15 × 0.8 = 0.12 | 1.0 × 2.5 = 2.5 | Hard to exit, restrictive entry to STATIONARY |
| Other | 0.15 (normal) | 1.0 (normal) | Normal entry thresholds |

### State Transition Flow

```
UNKNOWN → MOVING → HELD_STILL ⟷ STATIONARY
                      ↕
                   MOVING
```

**Key Improvement**: The ⟷ between HELD_STILL and STATIONARY now has asymmetric thresholds to prevent oscillation.

## Validation

### Test Scenarios

1. **Hold device steady by hand**:
   - ✅ Should settle in HELD_STILL and stay there
   - ✅ No oscillation between states

2. **Place on table**:
   - ✅ Should transition HELD_STILL → STATIONARY
   - ✅ Should stay in STATIONARY

3. **Pick up from table**:
   - ✅ Should transition STATIONARY → HELD_STILL/MOVING
   - ✅ Should require clear motion (hysteresis working)

### Debug Output to Monitor

Look for these patterns in the logs:

```bash
# Good - stable state
DEBUG - State change: MOVING → HELD_STILL
[... many samples with HELD_STILL, no state changes ...]

# Bad - oscillation (should be fixed now)
DEBUG - State change: HELD_STILL → STATIONARY  
DEBUG - State change: STATIONARY → HELD_STILL  # This should not happen repeatedly
```

## Performance Impact

- **Minimal**: Only affects state detection logic, not sensor reading performance
- **Improved responsiveness**: Reduced hysteresis factor from 3.0 to 2.5
- **Better accuracy**: Thresholds now match real-world usage patterns

## Files Modified

1. **`src/managers/accelerometer_manager.py`**:
   - Updated `_determine_stable_state()` with bidirectional hysteresis
   - Adjusted threshold values based on real data
   - Added debug logging for state transitions

2. **`debug_freefall_ultra_optimized.py`**:
   - Updated to show new threshold values
   - Improved debug output formatting

## Testing Instructions

1. **Deploy the updated code**:
   ```bash
   ./deploy_optimizations.sh pi@your-pi-ip /path/to/phoenix-vapi
   ```

2. **Test hand-held stability**:
   ```bash
   ./debug_freefall_ultra_optimized.py
   # Hold device steady by hand - should show HELD_STILL without oscillation
   ```

3. **Test table placement**:
   ```bash
   # Place device on stable table - should show STATIONARY
   # Pick up device - should transition to HELD_STILL/MOVING
   ```

## Success Criteria

- ✅ **No rapid oscillation** between STATIONARY and HELD_STILL
- ✅ **Stable HELD_STILL state** when holding device by hand
- ✅ **Clear STATIONARY state** when device is on table
- ✅ **Responsive transitions** when motion actually changes
- ✅ **Detailed debug logs** showing threshold comparisons

This fix should eliminate the state oscillation issue while maintaining accurate motion detection for free fall and other motion patterns. 