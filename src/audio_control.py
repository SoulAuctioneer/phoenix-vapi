import pyaudio

class AudioControl:
    def __init__(self):
        self._volume = 1.0  # Range 0.0 to 1.0
        self._pa = pyaudio.PyAudio()
        
    @property
    def volume(self):
        """Get current volume multiplier (0.0 to 1.0)"""
        return self._volume
    
    @volume.setter
    def volume(self, value):
        """Set volume multiplier (0.0 to 1.0)"""
        if not 0.0 <= value <= 1.0:
            raise ValueError("Volume must be between 0.0 and 1.0")
        self._volume = value
    
    def adjust_stream_volume(self, audio_data):
        """
        Adjust the volume of an audio stream by multiplying the samples.
        
        :param audio_data: The audio data as bytes
        :return: Volume-adjusted audio data as bytes
        """
        # Convert bytes to array of signed shorts
        import array
        samples = array.array('h')
        samples.frombytes(audio_data)
        
        # Apply volume
        for i in range(len(samples)):
            samples[i] = int(samples[i] * self._volume)
        
        return samples.tobytes()
    
    def cleanup(self):
        """Cleanup PyAudio resources"""
        self._pa.terminate() 