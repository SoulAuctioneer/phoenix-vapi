#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <stdint.h>

namespace py = pybind11;

// Forward declarations of C functions
extern "C" {
    int audio_core_init(void);
    void audio_core_cleanup(void);
    int audio_core_create_producer(int buffer_size);
    int audio_core_write_samples(int producer_id, const float* samples, int num_samples);
    int audio_core_write_samples_int16(int producer_id, const int16_t* samples, int num_samples);
    void audio_core_set_volume(int producer_id, float volume);
    void audio_core_set_active(int producer_id, int active);
}

// Python wrapper class
class AudioCore {
public:
    AudioCore() {
        if (audio_core_init() != 0) {
            throw std::runtime_error("Failed to initialize audio core");
        }
    }
    
    ~AudioCore() {
        audio_core_cleanup();
    }
    
    int create_producer(int buffer_size) {
        return audio_core_create_producer(buffer_size);
    }
    
    int write_samples(int producer_id, py::array_t<float> samples) {
        auto buf = samples.request();
        return audio_core_write_samples(producer_id, 
                                      static_cast<const float*>(buf.ptr),
                                      buf.size);
    }

    int write_samples_int16(int producer_id, py::array_t<int16_t> samples) {
        auto buf = samples.request();
        return audio_core_write_samples_int16(producer_id,
                                            static_cast<const int16_t*>(buf.ptr),
                                            buf.size);
    }
    
    void set_volume(int producer_id, float volume) {
        audio_core_set_volume(producer_id, volume);
    }
    
    void set_active(int producer_id, bool active) {
        audio_core_set_active(producer_id, active ? 1 : 0);
    }
};

PYBIND11_MODULE(audio_core, m) {
    py::class_<AudioCore>(m, "AudioCore")
        .def(py::init<>())
        .def("create_producer", &AudioCore::create_producer)
        .def("write_samples", &AudioCore::write_samples)
        .def("write_samples_int16", &AudioCore::write_samples_int16)
        .def("set_volume", &AudioCore::set_volume)
        .def("set_active", &AudioCore::set_active);
} 