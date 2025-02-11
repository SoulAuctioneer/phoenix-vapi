cmake_minimum_required(VERSION 3.10)
project(audio_core)

# Find Python
find_package(Python COMPONENTS Interpreter Development REQUIRED)

# Find pybind11
find_package(pybind11 REQUIRED)

# Get absolute path to src/core directory
get_filename_component(CORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}" ABSOLUTE)

# Set up PortAudio paths for macOS (Homebrew)
if(APPLE)
    set(PORTAUDIO_INCLUDE_DIRS "/opt/homebrew/include")
    set(PORTAUDIO_LIBRARIES "/opt/homebrew/lib/libportaudio.dylib")
endif()

# Add the C library
add_library(audio_core_lib STATIC
    audio_core.c
)

target_include_directories(audio_core_lib
    PRIVATE
    ${PORTAUDIO_INCLUDE_DIRS}
)

target_link_libraries(audio_core_lib
    PRIVATE
    ${PORTAUDIO_LIBRARIES}
)

# Add the Python module
pybind11_add_module(audio_core 
    audio_core.cpp
)

target_include_directories(audio_core
    PRIVATE
    ${PORTAUDIO_INCLUDE_DIRS}
)

target_link_libraries(audio_core
    PRIVATE
    audio_core_lib
    ${PORTAUDIO_LIBRARIES}
)

# Install the module to the src/core directory using absolute path
install(TARGETS audio_core 
    LIBRARY DESTINATION "${CORE_DIR}"
) 