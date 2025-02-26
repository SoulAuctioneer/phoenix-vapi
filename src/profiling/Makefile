# Makefile for audio profiling tools
.PHONY: all cprofile line_profile pyspy memory_profile cprofile_main line_profile_main install_deps help

# Default duration for profiling
DURATION ?= 30

help:
	@echo "Audio Manager and Phoenix Application Profiling Tools"
	@echo ""
	@echo "Usage:"
	@echo "  make install_deps         Install dependencies for profiling"
	@echo "  make cprofile             Run cProfile on AudioManager for $(DURATION) seconds"
	@echo "  make line_profile         Run line_profiler on AudioManager for $(DURATION) seconds"
	@echo "  make memory_profile       Run memory profiling on AudioManager for $(DURATION) seconds"
	@echo "  make cprofile_main        Run cProfile on the entire Phoenix application for $(DURATION) seconds"
	@echo "  make line_profile_main    Run line_profiler on the entire Phoenix application for $(DURATION) seconds"
	@echo "  make pyspy                Run py-spy on running Phoenix application for $(DURATION) seconds"
	@echo "  make visualize_cprofile   Visualize cProfile results with snakeviz (if installed)"
	@echo "  make track_memory         Track memory usage over time (requires mprof from memory_profiler)"
	@echo ""
	@echo "Parameters:"
	@echo "  DURATION=<seconds>        Set profiling duration (default: $(DURATION))"
	@echo "  PID=<process_id>          Set specific PID for py-spy (default: auto-detect)"
	@echo ""

all: cprofile line_profile pyspy memory_profile cprofile_main line_profile_main

# Install profiling dependencies
install_deps:
	@echo "Installing profiling dependencies..."
	pip install line_profiler psutil py-spy snakeviz memory_profiler

# Create profiling directory
create_dir:
	@mkdir -p .

# Run cProfile on AudioManager only
cprofile: create_dir
	@echo "Running cProfile on AudioManager for $(DURATION) seconds..."
	python profile_audio.py $(DURATION)

# Run line_profiler on AudioManager only
line_profile: create_dir
	@echo "Running line_profiler on AudioManager for $(DURATION) seconds..."
	python line_profile_audio.py $(DURATION)

# Run cProfile on the entire Phoenix application
cprofile_main: create_dir
	@echo "Running cProfile on entire Phoenix application for $(DURATION) seconds..."
	python profile_main_app.py --duration $(DURATION)

# Run line_profiler on the entire Phoenix application
line_profile_main: create_dir
	@echo "Running line_profiler on entire Phoenix application for $(DURATION) seconds..."
	python line_profile_main_app.py --duration $(DURATION)

# Run memory profiler on AudioManager
memory_profile: create_dir
	@echo "Running memory profiler for $(DURATION) seconds..."
	python memory_profile_audio.py $(DURATION)

# Track memory usage over time
track_memory: create_dir
	@echo "Tracking memory usage for $(DURATION) seconds..."
	mprof run --interval 0.1 memory_profile_audio.py $(DURATION)
	mprof plot --output memory_usage_plot.png

# Visualize cProfile results with snakeviz
visualize_cprofile:
	@if [ -f audio_profile.prof ]; then \
		echo "Visualizing AudioManager profile with snakeviz..."; \
		snakeviz audio_profile.prof; \
	elif [ -f main_app_profile.prof ]; then \
		echo "Visualizing Main App profile with snakeviz..."; \
		snakeviz main_app_profile.prof; \
	else \
		echo "Profile file not found. Run 'make cprofile' or 'make cprofile_main' first."; \
	fi

# Run py-spy on running Phoenix application
pyspy: create_dir
	@echo "Running py-spy for $(DURATION) seconds..."
	python pyspy_monitor.py --duration $(DURATION) $(if $(PID),--pid $(PID),) 