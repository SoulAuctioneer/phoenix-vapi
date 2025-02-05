import numpy as np
from multiprocessing import Process, Queue, cpu_count
import threading
import logging
import time
from typing import Optional, List, Dict, Callable, Any, NamedTuple
from queue import Empty
from dataclasses import dataclass
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from statistics import mean

class ProcessingStats(NamedTuple):
    """Statistics for monitoring processor performance"""
    tasks_processed: int
    tasks_timed_out: int
    avg_processing_time: float
    avg_queue_size: float
    current_queue_sizes: List[int]

@dataclass
class AudioTask:
    """Represents an audio processing task"""
    task_id: str
    operation: str
    data: Any
    callback: Callable[[Any], None]
    priority: int = 0  # Higher number = higher priority
    timestamp: float = 0.0  # When the task was created

class AudioProcessor(Process):
    """Individual audio processor running in its own process"""
    def __init__(self, input_queue: Queue, output_queue: Queue, processor_id: int):
        super().__init__()
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.processor_id = processor_id
        self.running = True
        self._processing_times = deque(maxlen=100)  # Track last 100 processing times
        
    def run(self):
        """Main process loop"""
        logging.info(f"Audio processor {self.processor_id} started")
        while self.running:
            try:
                task = self.input_queue.get(timeout=0.1)
                if task is None:  # Shutdown signal
                    break
                    
                task_id, operation, data, priority, timestamp = task
                start_time = time.time()
                
                try:
                    if operation == "resize":
                        chunk_size, audio_data, remainder = data
                        result = self._resize_chunk(chunk_size, audio_data, remainder)
                    elif operation == "mix":
                        chunks = data
                        result = self._mix_audio(chunks)
                    elif operation == "volume":
                        audio_data, volume = data
                        result = self._apply_volume(audio_data, volume)
                    
                    processing_time = time.time() - start_time
                    self._processing_times.append(processing_time)
                    
                    self.output_queue.put((task_id, result, processing_time))
                    
                except Exception as e:
                    logging.error(f"Error processing task {task_id} in processor {self.processor_id}: {e}")
                    self.output_queue.put((task_id, None, 0.0))  # Signal error to main thread
                    
            except Empty:
                continue
            except Exception as e:
                logging.error(f"Error in processor {self.processor_id}: {e}")
                continue
                
        logging.info(f"Audio processor {self.processor_id} stopped")
                
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
    """Manages a pool of audio processors with load balancing and monitoring"""
    def __init__(self, num_processors: Optional[int] = None):
        if num_processors is None:
            num_processors = max(1, cpu_count() - 1)  # Leave one core free for other tasks
        self.num_processors = num_processors
        self.processors: List[AudioProcessor] = []
        self.input_queues: List[Queue] = []
        self.output_queues: List[Queue] = []
        
        # Task tracking
        self._pending_tasks: Dict[str, AudioTask] = {}
        self._tasks_lock = threading.Lock()
        self._result_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Performance monitoring
        self._stats = {
            'tasks_processed': 0,
            'tasks_timed_out': 0,
            'processing_times': deque(maxlen=1000),
            'queue_sizes': deque(maxlen=1000)
        }
        self._stats_lock = threading.Lock()
        
        # Thread pool for callbacks
        self._callback_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="audio_callback")
        
    def start(self):
        """Start all processors and result handling thread"""
        self._running = True
        
        # Start processors
        for i in range(self.num_processors):
            input_queue = Queue()
            output_queue = Queue()
            processor = AudioProcessor(input_queue, output_queue, i)
            processor.start()
            self.processors.append(processor)
            self.input_queues.append(input_queue)
            self.output_queues.append(output_queue)
            
        # Start result handling thread
        self._result_thread = threading.Thread(target=self._handle_results, name="AudioProcessorResults")
        self._result_thread.daemon = True
        self._result_thread.start()
        
        logging.info(f"Started AudioProcessorPool with {self.num_processors} processors")
            
    def stop(self):
        """Stop all processors and result handling thread"""
        self._running = False
        
        # Stop callback executor
        self._callback_executor.shutdown(wait=False)
        
        # Stop processors
        for processor in self.processors:
            processor.stop()
        for processor in self.processors:
            processor.join()
            
        # Wait for result thread
        if self._result_thread:
            self._result_thread.join(timeout=1.0)
            
        # Clear everything
        self.processors.clear()
        self.input_queues.clear()
        self.output_queues.clear()
        with self._tasks_lock:
            self._pending_tasks.clear()
            
        logging.info("AudioProcessorPool stopped")
        
    def process_audio_async(self, operation: str, data: any, callback: Callable[[Any], None], priority: int = 0):
        """Process audio data asynchronously using the processor with the shortest queue"""
        if not self.processors:
            raise RuntimeError("AudioProcessorPool not started")
            
        # Create task
        task_id = str(uuid4())
        timestamp = time.time()
        task = AudioTask(task_id, operation, data, callback, priority, timestamp)
        
        # Store task
        with self._tasks_lock:
            self._pending_tasks[task_id] = task
        
        # Find processor with shortest queue
        queue_sizes = [q.qsize() for q in self.input_queues]
        processor_idx = queue_sizes.index(min(queue_sizes))
        
        # Update stats
        with self._stats_lock:
            self._stats['queue_sizes'].append(mean(queue_sizes))
        
        # Send task to processor
        self.input_queues[processor_idx].put((task_id, operation, data, priority, timestamp))
        
    def get_stats(self) -> ProcessingStats:
        """Get current processing statistics"""
        with self._stats_lock:
            return ProcessingStats(
                tasks_processed=self._stats['tasks_processed'],
                tasks_timed_out=self._stats['tasks_timed_out'],
                avg_processing_time=mean(self._stats['processing_times']) if self._stats['processing_times'] else 0,
                avg_queue_size=mean(self._stats['queue_sizes']) if self._stats['queue_sizes'] else 0,
                current_queue_sizes=[q.qsize() for q in self.input_queues]
            )
        
    def _handle_results(self):
        """Handle results from all processors"""
        while self._running:
            # Check all output queues
            for queue in self.output_queues:
                try:
                    task_id, result, processing_time = queue.get_nowait()
                    
                    # Update processing time stats
                    with self._stats_lock:
                        self._stats['processing_times'].append(processing_time)
                        self._stats['tasks_processed'] += 1
                    
                    # Get and remove task
                    with self._tasks_lock:
                        task = self._pending_tasks.pop(task_id, None)
                        
                    # Execute callback if task exists
                    if task and result is not None:
                        self._callback_executor.submit(task.callback, result)
                            
                except Empty:
                    continue
                except Exception as e:
                    logging.error(f"Error handling audio processing result: {e}")
                    continue
            
            # Small sleep to prevent busy waiting
            threading.Event().wait(0.001)