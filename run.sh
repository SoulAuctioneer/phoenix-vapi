echo "Starting Phoenix App"
if [ -z "$VIRTUAL_ENV" ]; then
    source venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
cd src && sudo python3 main.py
echo "Phoenix App Exited"
