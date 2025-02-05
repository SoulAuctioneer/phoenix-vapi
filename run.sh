echo "Starting Phoenix App"
if [ -z "$VIRTUAL_ENV" ]; then
    source venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
sudo "$(which python3)" src/main.py
echo "Phoenix App Exited"
