import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

class MemoryManager:
    """
    Manages storing and retrieving memories from VAPI calls.
    Memories are stored in a local JSON file and can be retrieved for use in future conversations.
    """
    
    def __init__(self, memory_file_path: str = "memories.json"):
        """
        Initialize the MemoryManager with a path to the memory file.
        
        Args:
            memory_file_path (str): Path to the JSON file where memories will be stored
        """
        self.memory_file_path = memory_file_path
        self._ensure_memory_file_exists()
        
    def _ensure_memory_file_exists(self):
        """Create the memory file if it doesn't exist"""
        if not os.path.exists(self.memory_file_path):
            with open(self.memory_file_path, 'w') as f:
                json.dump({"memories": []}, f)
                
    def _load_memories(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load memories from the JSON file"""
        try:
            with open(self.memory_file_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Error reading memory file {self.memory_file_path}. Creating new memory store.")
            return {"memories": []}
            
    def _save_memories(self, memories: Dict[str, List[Dict[str, Any]]]):
        """Save memories to the JSON file"""
        with open(self.memory_file_path, 'w') as f:
            json.dump(memories, f, indent=2)
            
    async def store_call_memories(self, call_id: str, memories: List[Dict[str, Any]]):
        """
        Store memories from a VAPI call.
        
        Args:
            call_id (str): The ID of the VAPI call
            memories (List[Dict[str, Any]]): List of memory objects from the call
        """
        current_memories = self._load_memories()
        
        # Add timestamp and call_id to each memory
        timestamp = datetime.utcnow().isoformat()
        for memory in memories:
            memory.update({
                "call_id": call_id,
                "timestamp": timestamp
            })
            
        current_memories["memories"].extend(memories)
        self._save_memories(current_memories)
        logging.info(f"Stored {len(memories)} memories from call {call_id}")
        
    def get_memories(self, 
                    call_id: Optional[str] = None, 
                    start_time: Optional[str] = None,
                    end_time: Optional[str] = None,
                    limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve memories with optional filtering.
        
        Args:
            call_id (str, optional): Filter memories by specific call ID
            start_time (str, optional): ISO format datetime string to filter memories after this time
            end_time (str, optional): ISO format datetime string to filter memories before this time
            limit (int, optional): Maximum number of memories to return
            
        Returns:
            List[Dict[str, Any]]: List of matching memories
        """
        memories = self._load_memories()["memories"]
        
        # Apply filters
        if call_id:
            memories = [m for m in memories if m.get("call_id") == call_id]
            
        if start_time:
            memories = [m for m in memories if m.get("timestamp", "") >= start_time]
            
        if end_time:
            memories = [m for m in memories if m.get("timestamp", "") <= end_time]
            
        # Sort by timestamp descending (newest first)
        memories.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Apply limit if specified
        if limit:
            memories = memories[:limit]
            
        return memories
        
    def clear_memories(self, call_id: Optional[str] = None):
        """
        Clear all memories or memories from a specific call.
        
        Args:
            call_id (str, optional): If provided, only clear memories from this call
        """
        if call_id:
            current_memories = self._load_memories()
            current_memories["memories"] = [m for m in current_memories["memories"] 
                                         if m.get("call_id") != call_id]
            self._save_memories(current_memories)
            logging.info(f"Cleared memories for call {call_id}")
        else:
            self._save_memories({"memories": []})
            logging.info("Cleared all memories") 

    async def _get_call_record(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve the call record from VAPI API.
        
        Args:
            call_id (str): The ID of the call to retrieve
            
        Returns:
            Dict[str, Any]: The call record containing memories and other data
        """
        url = f"{self.api_url}/call/{call_id}"
        headers = {
            'Authorization': 'Bearer ' + self.api_key,
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Failed to retrieve call record for {call_id}: {e}")
            raise