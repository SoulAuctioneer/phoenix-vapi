#!/bin/bash
"""
Deployment script for BNO085 optimizations to Raspberry Pi
Usage: ./deploy_optimizations.sh pi@your-pi-ip /path/to/phoenix-vapi
"""

# Check arguments
if [ $# -ne 2 ]; then
    echo "Usage: $0 <pi-user@pi-ip> <remote-path>"
    echo "Example: $0 pi@192.168.1.100 /home/pi/phoenix-vapi"
    exit 1
fi

PI_HOST=$1
REMOTE_PATH=$2

echo "🚀 Deploying BNO085 optimizations to $PI_HOST:$REMOTE_PATH"
echo "=================================================="

# Create remote directory if it doesn't exist
echo "📁 Creating remote directory..."
ssh $PI_HOST "mkdir -p $REMOTE_PATH"

# Copy optimized source files
echo "📦 Copying optimized source files..."
scp -r src/ $PI_HOST:$REMOTE_PATH/

# Copy new scripts
echo "🔧 Copying calibration and debug scripts..."
scp calibrate_bno085.py $PI_HOST:$REMOTE_PATH/
scp debug_freefall_ultra_optimized.py $PI_HOST:$REMOTE_PATH/
scp debug_freefall_optimized.py $PI_HOST:$REMOTE_PATH/

# Copy documentation
echo "📚 Copying documentation..."
scp BNO085_OPTIMIZATION_README.md $PI_HOST:$REMOTE_PATH/
scp OPTIMIZATION_SUMMARY.md $PI_HOST:$REMOTE_PATH/

# Make scripts executable
echo "🔐 Making scripts executable..."
ssh $PI_HOST "chmod +x $REMOTE_PATH/calibrate_bno085.py"
ssh $PI_HOST "chmod +x $REMOTE_PATH/debug_freefall_ultra_optimized.py"
ssh $PI_HOST "chmod +x $REMOTE_PATH/debug_freefall_optimized.py"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps on Raspberry Pi:"
echo "1. SSH to Pi: ssh $PI_HOST"
echo "2. Navigate: cd $REMOTE_PATH"
echo "3. Run calibration: ./calibrate_bno085.py"
echo "4. Test performance: ./debug_freefall_ultra_optimized.py"
echo ""
echo "Expected performance improvement: 20-50x faster (from 300-1000ms to 5-15ms)"
echo "Target: <10ms read times with stable state detection" 