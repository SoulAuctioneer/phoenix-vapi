import threading
import logging
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum

class ThreadState(Enum):
    """States for the audio thread"""
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

@dataclass
class ThreadStats:
    """Statistics for thread monitoring"""
    start_time: float
    iterations: int
    errors: int
    last_error: Optional[str]
    last_active: float

class AudioThread:
    """Thread management for audio processing"""
    def __init__(
        self,
        target: Callable[..., Any],
        name: str,
        args: tuple = (),
        kwargs: dict = None,
        error_handler: Optional[Callable[[Exception], None]] = None,
        restart_on_error: bool = True,
        max_restarts: int = 3,
        restart_delay: float = 1.0
    ):
        self.target = target
        self.name = name
        self.args = args
        self.kwargs = kwargs or {}
        self.error_handler = error_handler
        self.restart_on_error = restart_on_error
        self.max_restarts = max_restarts
        self.restart_delay = restart_delay
        
        self._thread: Optional[threading.Thread] = None
        self._state = ThreadState.INITIALIZED
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._restart_count = 0
        
        # Statistics
        self._stats = ThreadStats(
            start_time=0.0,
            iterations=0,
            errors=0,
            last_error=None,
            last_active=0.0
        )
        
    @property
    def state(self) -> ThreadState:
        """Get current thread state"""
        with self._state_lock:
            return self._state
            
    @property
    def stats(self) -> ThreadStats:
        """Get thread statistics"""
        return self._stats
        
    def start(self):
        """Start the audio thread"""
        with self._state_lock:
            if self._state not in [ThreadState.INITIALIZED, ThreadState.STOPPED]:
                return
                
            self._state = ThreadState.STARTING
            self._stop_event.clear()
            self._stats.start_time = time.time()
            self._thread = threading.Thread(
                target=self._run_wrapper,
                name=self.name,
                daemon=True
            )
            self._thread.start()
            
    def stop(self, timeout: float = 5.0):
        """Stop the audio thread"""
        with self._state_lock:
            if self._state not in [ThreadState.RUNNING, ThreadState.ERROR]:
                return
                
            self._state = ThreadState.STOPPING
            self._stop_event.set()
            
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logging.warning(f"Thread {self.name} did not stop within timeout")
                
        with self._state_lock:
            self._state = ThreadState.STOPPED
            
    def _run_wrapper(self):
        """Wrapper around the target function to handle errors and restarts"""
        while not self._stop_event.is_set():
            try:
                with self._state_lock:
                    self._state = ThreadState.RUNNING
                    
                self.target(*self.args, **self.kwargs)
                self._stats.iterations += 1
                self._stats.last_active = time.time()
                
            except Exception as e:
                self._stats.errors += 1
                self._stats.last_error = str(e)
                logging.error(f"Error in thread {self.name}: {e}")
                
                if self.error_handler:
                    try:
                        self.error_handler(e)
                    except Exception as handler_error:
                        logging.error(f"Error in error handler for thread {self.name}: {handler_error}")
                        
                with self._state_lock:
                    self._state = ThreadState.ERROR
                    
                if self.restart_on_error and self._restart_count < self.max_restarts:
                    self._restart_count += 1
                    logging.info(f"Restarting thread {self.name} ({self._restart_count}/{self.max_restarts})")
                    time.sleep(self.restart_delay)
                    continue
                else:
                    break
                    
        with self._state_lock:
            self._state = ThreadState.STOPPED
            
    def is_alive(self) -> bool:
        """Check if the thread is alive"""
        return self._thread is not None and self._thread.is_alive()
        
    def reset_stats(self):
        """Reset thread statistics"""
        self._stats = ThreadStats(
            start_time=time.time() if self.is_alive() else 0.0,
            iterations=0,
            errors=0,
            last_error=None,
            last_active=time.time() if self.is_alive() else 0.0
        )
        self._restart_count = 0 