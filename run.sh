echo "Starting Phoenix App"
if [ -z "$VIRTUAL_ENV" ]; then
    source venv/bin/activate
fi
sudo python3 src/main.py
echo "Phoenix App Exited"
