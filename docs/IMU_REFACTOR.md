# AccelerometerManager Refactoring Plan (Post-IMU Repositioning)

## 1. Context and Goal

The IMU (BNO085) has been repositioned within the spherical device to be significantly closer to the center of rotation:
- Centered on X-axis (0mm offset)
- ~10mm offset on Y-axis
- ~2mm offset on Z-axis

Previously, a large off-center position induced significant, oscillating linear acceleration readings during rolling (due to centripetal force), making it extremely difficult to reliably distinguish `ROLLING` patterns from `SHAKE` patterns. This led to complex detection logic involving acceleration variance, fine-tuned gyro dominance checks, and mutual exclusion rules.

**Goal:** Leverage the new, near-center IMU position to:
1.  **Simplify** the `AccelerometerManager` code, removing complexity introduced specifically to handle the old offset issue.
2.  **Improve reliability and robustness** of motion state and pattern detection (especially `SHAKE` vs. `ROLLING`).

## 2. Key Impact of New IMU Position

-   **Reduced Centripetal Acceleration:** The primary benefit. The `a = ω²r` effect will be drastically smaller, especially due to the 0mm X and 2mm Z offsets. The 10mm Y offset will still contribute, but likely much less confusingly than before.
-   **Clearer Rolling Signature:** Rolling should now exhibit:
    -   More stable (though non-zero due to gravity and the Y-offset) linear acceleration.
    -   Consistent gyroscope rotation around a dominant axis.
-   **Clearer Shake Signature:** Shaking should still show erratic, high-variance acceleration and potentially erratic/non-dominant rotation, but *without* the strong, periodic centripetal acceleration mimicking it during rolls.
-   **Potential for Threshold Simplification:** Thresholds previously tuned to reject rolling artifacts during shake detection (e.g., high variance thresholds) or carefully define rolling boundaries might be simplified or relaxed.

## 3. Refactoring Strategy

The core philosophy is **simplification first**. Assume the improved physics makes detection easier and remove complexity added for the old problem. Re-tune from a simpler baseline if necessary.

**3.1. Shake Detection (`_check_shake_pattern`)**

-   **Hypothesis:** The complexity (variance check, nuanced gyro dominance/magnitude logic, specific `shake_history_size`) might be unnecessary now.
-   **Proposal:**
    -   **Temporarily remove variance:** Comment out or remove the `statistics.variance` check (`min_accel_variance_for_shake`).
    -   **Simplify Gyro Check:** Initially, simplify or even remove the gyro checks (`high_gyro_magnitude_threshold`, `max_gyro_dominance_ratio`). Perhaps a simple check for high *average* gyro magnitude is enough, or maybe acceleration alone will suffice.
    -   **Revisit History Size:** Start with a smaller `shake_history_size` (e.g., 5-10 samples / ~0.05-0.1s) to focus on rapid changes.
    -   **Focus on Acceleration Reversals/Magnitude:** Consider if a simpler check (e.g., counting zero-crossings of acceleration components, or just average magnitude above a threshold) is now sufficient.
-   **Rationale:** With rolling artifacts reduced, a simpler signature for shaking might emerge.
-   **Cross-Validation:** Ensure the simplified shake logic is tested against throw acceleration peaks and catch impact spikes to avoid false positives after mutual exclusion removal.

**3.2. Rolling Detection (`_check_rolling_pattern`, `_check_rolling_criteria`)**

-   **Hypothesis:** This should become more reliable. The core logic (duration, gyro magnitude, dominant axis) is likely still correct, but thresholds might change.
-   **Proposal:**
    -   **Verify Thresholds:** Review `rolling_accel_min`, `rolling_accel_max`, `rolling_gyro_min`, and `rolling_duration`. Start with reasonable physical estimates. The `rolling_accel_max` might be lower now if high peaks were due to the old offset.
    -   **Emphasize Dominant Axis:** The `_dominant_rotation_axis` check is likely *more* reliable now and remains key. Ensure the `min_dominant_ratio` threshold (e.g., 0.35-0.55) makes sense.
    -   **Retain Linear Motion Check:** Keep the `if self._check_linear_motion(): return False` guard, as sliding is distinct from rolling.
-   **Rationale:** Rolling detection should be less about filtering noise and more about positively identifying the rolling characteristics.
-   **Cross-Validation:** Allow the system to detect patterns independently. If `SHAKE` and `ROLLING` (or others) are detected simultaneously, analyze *why*. It might indicate a need for tuning, or potentially represent a real combined motion (e.g., a shaky roll). Test specifically if simplified `SHAKE` logic falsely triggers on `THROW` or `CATCH`.

**3.3. Mutual Exclusion (`_detect_motion_patterns`)**

-   **Hypothesis:** The strict `if not is_shake:` guards might no longer be needed if `_check_shake_pattern` and `_check_rolling_pattern` are independently reliable.
-   **Proposal:**
    -   **Remove Prioritization:** Comment out or remove the `if not is_shake:` conditions that prevent checking for other patterns when `SHAKE` is detected.
    -   **Observe Overlap:** Allow the system to detect patterns independently. If `SHAKE` and `ROLLING` (or others) are detected simultaneously, analyze *why*. It might indicate a need for tuning, or potentially represent a real combined motion (e.g., a shaky roll).
-   **Rationale:** Simplifies control flow. Aims for detectors that work correctly on their own.

**3.4. State Machine (`_update_motion_state`)**

-   **Hypothesis:** Transitions involving `ROLLING` should be cleaner. Other core transitions (Idle, Accel, Free Fall, Impact) might need minor threshold review.
-   **Proposal:**
    -   **Review Rolling Transitions:** Examine `IDLE -> ROLLING`, `ACCELERATION -> ROLLING`, `LINEAR_MOTION -> ROLLING`, `HELD_STILL -> ROLLING` and transitions *out* of `ROLLING`. Ensure the reliance on `_check_rolling_criteria` and `_check_linear_motion` is logical.
    -   **Review Core Thresholds:** Briefly re-evaluate `throw_acceleration_threshold`, `free_fall_threshold`, `impact_threshold`. Were they inflated previously to avoid triggers during noisy rolling? They might be reducible to more standard, physically intuitive values now. Re-evaluate `impact_exit_threshold` as well.
-   **Rationale:** Ensure the state machine accurately reflects the physics now that rolling noise is reduced.

**3.5. Threshold Review (General)**

-   **Proposal:** Create a dedicated section or pass to review *all* numerical thresholds. Consider resetting them to simpler, physics-based defaults and re-tuning based on observations with the new setup, rather than inheriting values tuned for the old, problematic setup.

**3.6. Offset Compensation**

-   **Decision:** **Do not** add explicit mathematical compensation for the remaining Y (10mm) and Z (2mm) offsets at this stage.
-   **Rationale:**
    -   The BNO08x's sensor fusion likely handles gravity compensation adequately.
    -   The primary issue (centripetal acceleration) is greatly reduced by the near-centering.
    -   Adding compensation requires precise orientation knowledge and significantly increases complexity, which we are trying to avoid.
    -   Prioritize simplifying the detection logic first. If specific biases directly attributable to the remaining small offsets are observed *after* simplification, compensation could be reconsidered.

**3.7. Code Cleanup**

-   **Proposal:** Remove commented-out code blocks from previous experiments. Ensure logging messages are clear and informative for the upcoming tuning process.

## 4. Implementation Steps

1.  Implement the proposed simplifications for `_check_shake_pattern`.
2.  Remove the mutual exclusion logic in `_detect_motion_patterns`.
3.  Review and potentially adjust thresholds in `_check_rolling_pattern` and the state machine (`_update_motion_state`), favouring simpler/lower values initially.
4.  Perform systematic testing, observing:
    -   Pure rolling motion.
    -   Pure shaking motion.
    -   Throws, catches, drops.
    -   Arc swings.
    -   Transitions between states.
5.  Analyze logs, particularly cases where patterns might overlap or detection fails. Pay attention to potential false SHAKE detections during THROW/CATCH events.
6.  Iteratively re-introduce complexity *only if necessary* based on specific observed failures (e.g., re-enable variance or gyro checks for shake if simpler methods fail, adjust thresholds).
7.  Clean up code (comments, logging).

This structured approach aims to leverage the hardware improvement for significant code simplification and hopefully more robust performance. 