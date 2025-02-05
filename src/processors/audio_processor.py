import numpy as np
from multiprocessing import Process, Queue, cpu_count
import logging
from typing import Optional, List

class AudioProcessor(Process):
    def __init__(self, input_queue: Queue, output_queue: Queue):
        super().__init__()
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.running = True
        
    def run(self):
        """Main process loop"""
        while self.running:
            try:
                task = self.input_queue.get()
                if task is None:  # Shutdown signal
                    break
                    
                operation, data = task
                if operation == "resize":
                    chunk_size, audio_data, remainder = data
                    result = self._resize_chunk(chunk_size, audio_data, remainder)
                elif operation == "mix":
                    chunks = data
                    result = self._mix_audio(chunks)
                elif operation == "volume":
                    audio_data, volume = data
                    result = self._apply_volume(audio_data, volume)
                    
                self.output_queue.put(result)
                
            except Exception as e:
                logging.error(f"Error in AudioProcessor: {e}")
                continue
                
    def stop(self):
        """Stop the processor"""
        self.running = False
        self.input_queue.put(None)  # Send shutdown signal
        
    @staticmethod
    def _resize_chunk(chunk_size: int, audio_data: np.ndarray, remainder: np.ndarray) -> tuple:
        """Resize audio chunk to desired size, handling remainder samples"""
        if len(remainder) > 0:
            audio_data = np.concatenate([remainder, audio_data])
            
        chunks = []
        num_complete_chunks = len(audio_data) // chunk_size
        for i in range(num_complete_chunks):
            start = i * chunk_size
            end = start + chunk_size
            chunks.append(audio_data[start:end])
            
        remainder_start = num_complete_chunks * chunk_size
        new_remainder = audio_data[remainder_start:]
        
        return chunks, new_remainder
        
    @staticmethod
    def _mix_audio(chunks: List[np.ndarray]) -> np.ndarray:
        """Mix multiple audio chunks together"""
        if not chunks:
            return np.array([], dtype=np.int16)
            
        # Convert to float32 for mixing to prevent overflow
        mixed = np.zeros_like(chunks[0], dtype=np.float32)
        for chunk in chunks:
            mixed += chunk.astype(np.float32)
            
        # Normalize and convert back to int16
        if len(chunks) > 1:
            mixed /= len(chunks)
        return np.clip(mixed, -32768, 32767).astype(np.int16)
        
    @staticmethod
    def _apply_volume(audio_data: np.ndarray, volume: float) -> np.ndarray:
        """Apply volume control to audio data"""
        if volume == 1.0:
            return audio_data
        audio_float = audio_data.astype(np.float32) * volume
        return np.clip(audio_float, -32768, 32767).astype(np.int16)

class AudioProcessorPool:
    """Manages a pool of audio processors"""
    def __init__(self, num_processors: Optional[int] = None):
        if num_processors is None:
            num_processors = max(1, cpu_count() - 1)  # Leave one core free for other tasks
        self.num_processors = num_processors
        self.processors: List[AudioProcessor] = []
        self.input_queues: List[Queue] = []
        self.output_queues: List[Queue] = []
        self.next_processor = 0
        
    def start(self):
        """Start all processors"""
        for _ in range(self.num_processors):
            input_queue = Queue()
            output_queue = Queue()
            processor = AudioProcessor(input_queue, output_queue)
            processor.start()
            self.processors.append(processor)
            self.input_queues.append(input_queue)
            self.output_queues.append(output_queue)
            
    def stop(self):
        """Stop all processors"""
        for processor in self.processors:
            processor.stop()
        for processor in self.processors:
            processor.join()
        self.processors.clear()
        self.input_queues.clear()
        self.output_queues.clear()
        
    def process_audio(self, operation: str, data: any) -> any:
        """Process audio data using the next available processor"""
        if not self.processors:
            raise RuntimeError("AudioProcessorPool not started")
            
        # Simple round-robin distribution
        processor_idx = self.next_processor
        self.next_processor = (self.next_processor + 1) % self.num_processors
        
        self.input_queues[processor_idx].put((operation, data))
        return self.output_queues[processor_idx].get()