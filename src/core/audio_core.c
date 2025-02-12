#include <portaudio.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#define MAX_PRODUCERS 8
#define SAMPLE_RATE 16000
#define FRAMES_PER_BUFFER 640
#define DEFAULT_BUFFER_SIZE 32768  // Increased buffer size

typedef struct {
    float* buffer;
    int buffer_size;
    int read_pos;
    int write_pos;
    int active;
    float volume;
    int samples_available;  // Track available samples
} AudioProducer;

typedef struct {
    AudioProducer producers[MAX_PRODUCERS];
    int num_producers;
    PaStream* stream;
    float* mix_buffer;
} AudioEngine;

static AudioEngine* g_engine = NULL;

static int audioCallback(const void *inputBuffer, void *outputBuffer,
                        unsigned long framesPerBuffer,
                        const PaStreamCallbackTimeInfo* timeInfo,
                        PaStreamCallbackFlags statusFlags,
                        void *userData) {
    AudioEngine* engine = (AudioEngine*)userData;
    float* out = (float*)outputBuffer;
    
    // Clear mix buffer
    memset(engine->mix_buffer, 0, framesPerBuffer * sizeof(float));
    
    // Mix all active producers
    for (int p = 0; p < engine->num_producers; p++) {
        AudioProducer* producer = &engine->producers[p];
        if (!producer->active || producer->samples_available == 0) continue;
        
        // Mix this producer's data
        for (int i = 0; i < framesPerBuffer; i++) {
            if (producer->samples_available > 0) {
                int read_idx = (producer->read_pos + i) % producer->buffer_size;
                engine->mix_buffer[i] += producer->buffer[read_idx] * producer->volume;
                producer->samples_available--;
            }
        }
        
        // Update read position
        producer->read_pos = (producer->read_pos + framesPerBuffer) % producer->buffer_size;
    }
    
    // Scale and copy to output
    for (int i = 0; i < framesPerBuffer; i++) {
        out[i] = engine->mix_buffer[i] * 0.8f;  // Scale to prevent clipping
    }
    
    return paContinue;
}

int audio_core_init(void) {
    PaError err;
    
    // Initialize PortAudio
    err = Pa_Initialize();
    if (err != paNoError) goto error;
    
    // Allocate engine
    g_engine = (AudioEngine*)calloc(1, sizeof(AudioEngine));
    if (!g_engine) goto error;
    
    // Allocate mix buffer
    g_engine->mix_buffer = (float*)calloc(FRAMES_PER_BUFFER, sizeof(float));
    if (!g_engine->mix_buffer) goto error;
    
    // Open audio stream
    err = Pa_OpenDefaultStream(&g_engine->stream,
                             0,          // no input channels
                             1,          // mono output
                             paFloat32,  // sample format
                             SAMPLE_RATE,
                             FRAMES_PER_BUFFER,
                             audioCallback,
                             g_engine);
    if (err != paNoError) goto error;
    
    // Start stream
    err = Pa_StartStream(g_engine->stream);
    if (err != paNoError) goto error;
    
    return 0;
    
error:
    if (g_engine) {
        if (g_engine->mix_buffer) free(g_engine->mix_buffer);
        free(g_engine);
        g_engine = NULL;
    }
    Pa_Terminate();
    return -1;
}

void audio_core_cleanup(void) {
    if (!g_engine) return;
    
    // Stop and close stream
    if (g_engine->stream) {
        Pa_StopStream(g_engine->stream);
        Pa_CloseStream(g_engine->stream);
    }
    
    // Free producers
    for (int i = 0; i < g_engine->num_producers; i++) {
        if (g_engine->producers[i].buffer) {
            free(g_engine->producers[i].buffer);
        }
    }
    
    // Free engine
    if (g_engine->mix_buffer) free(g_engine->mix_buffer);
    free(g_engine);
    g_engine = NULL;
    
    Pa_Terminate();
}

int audio_core_create_producer(int buffer_size) {
    if (!g_engine || g_engine->num_producers >= MAX_PRODUCERS) return -1;
    
    // Use provided buffer size or default
    if (buffer_size <= 0) buffer_size = DEFAULT_BUFFER_SIZE;
    
    int idx = g_engine->num_producers++;
    AudioProducer* producer = &g_engine->producers[idx];
    
    producer->buffer = (float*)calloc(buffer_size, sizeof(float));
    if (!producer->buffer) return -1;
    
    producer->buffer_size = buffer_size;
    producer->read_pos = 0;
    producer->write_pos = 0;
    producer->active = 1;
    producer->volume = 1.0f;
    producer->samples_available = 0;
    
    return idx;
}

int audio_core_write_samples_int16(int producer_id, const int16_t* samples, int num_samples) {
    if (!g_engine || producer_id >= g_engine->num_producers) return -1;
    
    AudioProducer* producer = &g_engine->producers[producer_id];
    if (!producer->active) return -1;
    
    // Calculate available space
    int space_available = producer->buffer_size - producer->samples_available;
    if (space_available <= 0) return 0;  // Buffer is full
    
    // Write as many samples as we can
    int samples_to_write = (num_samples < space_available) ? num_samples : space_available;
    
    // Convert int16 to float32 during write
    for (int i = 0; i < samples_to_write; i++) {
        producer->buffer[producer->write_pos] = samples[i] / 32768.0f;  // Convert to -1.0 to 1.0 range
        producer->write_pos = (producer->write_pos + 1) % producer->buffer_size;
        producer->samples_available++;
    }
    
    return samples_to_write;
}

int audio_core_write_samples(int producer_id, const float* samples, int num_samples) {
    if (!g_engine || producer_id >= g_engine->num_producers) return -1;
    
    AudioProducer* producer = &g_engine->producers[producer_id];
    if (!producer->active) return -1;
    
    // Calculate available space
    int space_available = producer->buffer_size - producer->samples_available;
    if (space_available <= 0) return 0;  // Buffer is full
    
    // Write as many samples as we can
    int samples_to_write = (num_samples < space_available) ? num_samples : space_available;
    
    // Copy float samples directly
    for (int i = 0; i < samples_to_write; i++) {
        producer->buffer[producer->write_pos] = samples[i];
        producer->write_pos = (producer->write_pos + 1) % producer->buffer_size;
        producer->samples_available++;
    }
    
    return samples_to_write;
}

void audio_core_set_volume(int producer_id, float volume) {
    if (!g_engine || producer_id >= g_engine->num_producers) return;
    g_engine->producers[producer_id].volume = volume;
}

void audio_core_set_active(int producer_id, int active) {
    if (!g_engine || producer_id >= g_engine->num_producers) return;
    g_engine->producers[producer_id].active = active;
} 