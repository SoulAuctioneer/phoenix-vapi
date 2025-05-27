# BNO085 Accelerometer Performance Optimization

This document describes the performance optimizations implemented for the BNO085 accelerometer system to achieve faster sensor readings and more reliable free fall detection.

## Performance Improvements

### Before Optimization
- **Read Times**: 300-1000ms (extremely slow)
- **Sensors Enabled**: 6 sensors (acceleration, linear_acceleration, gyro, game_quaternion, stability, shake, calibration)
- **I2C Frequency**: 50Hz for motion sensors, 10Hz for classification
- **State Detection**: Unstable due to quaternion rotation noise

### After Optimization
- **Expected Read Times**: 5-15ms (target: <10ms)
- **Sensors Enabled**: 3 essential sensors only (acceleration, linear_acceleration, gyro)
- **I2C Frequency**: 50Hz for essential sensors only
- **State Detection**: Stable software-based detection

### Key Optimizations

1. **Removed Calibration from Main Loop**
   - Calibration status reading was taking 3-11ms per call
   - Moved to separate calibration script
   - Calibration only needed once, not every sensor read

2. **Disabled Non-Essential Sensors**
   - Removed: game_quaternion, stability_classifier, shake_detector
   - These were taking 6-7ms each and not essential for free fall detection
   - Implemented software-based shake detection instead

3. **Optimized Sensor Reading Function**
   - Created `read_sensor_data_optimized()` that only reads 3 sensors
   - Reduced I2C transactions from 6-7 to 3
   - Simplified data extraction and processing

4. **Software-Based State Detection**
   - Replaced BNO085 stability classification with software logic
   - Removed quaternion rotation speed calculation (was causing false motion)
   - More reliable and faster state transitions

## New Scripts and Tools

### 1. Calibration Script: `calibrate_bno085.py`

**Purpose**: Standalone calibration tool following BNO085 datasheet recommendations.

**Usage**:
```bash
./calibrate_bno085.py
```

**Features**:
- Guided calibration process for accelerometer, gyroscope, and magnetometer
- Real-time calibration status monitoring
- Automatic calibration data saving
- Based on manufacturer specifications

**When to Use**:
- First time setup
- After hardware changes
- If motion detection seems inaccurate
- Periodically for best performance

### 2. Ultra-Optimized Debug Script: `debug_freefall_ultra_optimized.py`

**Purpose**: Test the optimized sensor configuration and performance.

**Usage**:
```bash
./debug_freefall_ultra_optimized.py
```

**Features**:
- Only reads 3 essential sensors
- Detailed performance metrics (min/max/avg read times)
- Real-time state detection monitoring
- Performance comparison vs targets

**Expected Output**:
```
ULTRA-OPTIMIZED MODE: Only 3 essential sensors enabled
- Raw acceleration (for total magnitude)
- Linear acceleration (motion without gravity)
- Gyroscope (rotation detection)

[Sample] Time(ms) | State      | Raw(m/s²) | Linear(m/s²) | Gyro(rad/s) | Read(ms) | Calc(ms) | Total(ms) | Alerts
[   50]     8.2ms | STATIONARY |       9.7 |         0.03 |        0.00 |      7.1 |      0.0 |       7.1 | 
OPTIMIZED TIMING: Batch=5.2ms, Thread=1.0ms, Extract=0.0ms
SENSOR TIMINGS (3 only): acceleration=1.8, linear_acceleration=1.7, gyro=1.7
```

### 3. Original Debug Script: `debug_freefall_optimized.py`

**Purpose**: Compare performance with the original configuration.

**Usage**: For comparison testing only.

## Technical Details

### Essential Sensors for Free Fall Detection

1. **Raw Acceleration** (`acceleration`)
   - Provides total acceleration magnitude including gravity
   - Used to detect low acceleration during free fall
   - Threshold: <7.0 m/s² for free fall detection

2. **Linear Acceleration** (`linear_acceleration`)
   - Acceleration with gravity removed
   - Used for motion state classification
   - More accurate for detecting device movement

3. **Gyroscope** (`gyro`)
   - Angular velocity in rad/s
   - Detects rotational motion during free fall
   - Threshold: >1.0 rad/s for free fall confirmation

### Disabled Sensors (For Performance)

- **Game Quaternion**: Not essential for free fall, was taking 6-7ms
- **Stability Classifier**: Replaced with software logic
- **Shake Detector**: Replaced with software algorithm
- **Magnetometer**: Not needed for free fall detection
- **Calibration Status**: Moved to separate script

### State Detection Logic

The optimized system uses software-based state detection:

- **STATIONARY**: Linear accel <0.25 m/s², gyro <0.10 rad/s
- **HELD_STILL**: Linear accel <0.80 m/s², gyro <0.25 rad/s  
- **FREE_FALL**: Total accel <7.0 m/s² AND gyro >1.0 rad/s
- **IMPACT**: Sudden acceleration spike >15.0 m/s²
- **SHAKE**: Software-based rapid acceleration changes
- **MOVING**: Default state for other motion

### Hysteresis and Stability

- **Hysteresis Factor**: 3.0x (prevents rapid state oscillation)
- **Minimum State Duration**: 0.5s (prevents flickering)
- **State Transition Logic**: Prioritizes critical states (FREE_FALL, IMPACT)

## Performance Targets

| Metric | Target | Previous | Expected |
|--------|--------|----------|----------|
| Read Time | <10ms | 300-1000ms | 5-15ms |
| I2C Transactions | 3 | 6-7 | 3 |
| Sensor Frequency | 50Hz | 50Hz | 50Hz |
| State Stability | Stable | Oscillating | Stable |

## Usage Recommendations

### For Production Use

1. **Run calibration first**:
   ```bash
   ./calibrate_bno085.py
   ```

2. **Use optimized configuration**:
   - The system automatically uses `read_sensor_data_optimized()`
   - Only essential sensors are enabled
   - Calibration is not read in main loop

3. **Monitor performance**:
   - Use ultra-optimized debug script to verify performance
   - Target read times should be <10ms consistently

### For Development/Testing

1. **Compare performance**:
   - Run both debug scripts to compare old vs new performance
   - Monitor timing breakdowns and sensor-specific delays

2. **Validate state detection**:
   - Test free fall scenarios
   - Verify state transitions are stable
   - Check for false positives/negatives

### For Troubleshooting

1. **If reads are still slow (>15ms)**:
   - Check I2C bus health
   - Consider software I2C (see hardware interface options)
   - Verify only 3 sensors are enabled

2. **If state detection is unstable**:
   - Run calibration script
   - Check threshold values
   - Verify hysteresis settings

3. **If free fall detection is inaccurate**:
   - Calibrate sensors
   - Test with actual free fall scenarios
   - Adjust thresholds if needed

## Future Optimizations

### Potential Further Improvements

1. **Software I2C**: May provide better reliability
2. **Lower I2C Baud Rate**: Could reduce electrical noise
3. **Sensor Fusion on Pi**: Calculate quaternions on Raspberry Pi instead of BNO085
4. **Batch Reading**: Read multiple samples in one I2C transaction

### Hardware Considerations

- **I2C Bus Speed**: Currently 400kHz, could experiment with lower speeds
- **Pull-up Resistors**: Ensure proper I2C signal integrity
- **Power Supply**: Stable power reduces sensor noise
- **Physical Mounting**: Reduce vibration for better readings

## Conclusion

These optimizations should provide a 20-50x improvement in sensor read performance while maintaining or improving the accuracy of free fall detection. The separation of calibration from the main loop and the focus on only essential sensors significantly reduces I2C overhead and improves system responsiveness. 