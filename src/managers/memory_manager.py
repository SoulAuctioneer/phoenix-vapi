import json
import os
import logging
from datetime import datetime, timezone
import time
from textwrap import dedent
from typing import Dict, List, Optional, Any
import openai


class MemoryManager:
    """
    Manages storing and retrieving memories about the user.
    Memories are stored in a local JSON file and can be retrieved for use in future conversations.
    """
    
    # Prompt for memory extraction
    MEMORY_EXTRACTION_PROMPT_TEMPLATE = dedent("""
    You are an assistant that analyzes conversations and extracts important memories or facts.
    Extract key information that would be useful for future conversations.
    Return the memories as a list of JSON objects, each with the following structure:
    [
      {{
        "content": "The specific memory or fact",
        "topic": "A short topic label for categorization",
        "importance": "high/medium/low"
      }}
    ]
    
    The "topic" field MUST be one of the following values only:
    - "preference" (for user likes, dislikes, and preferences)
    - "fact" (for factual information about the user)
    - "event" (for events in the user's life)
    - "conversation_topic" (for topics discussed)
    - "activity" (for briefly describing any activities played together)
    - "story_progress" (for summarizing a story activity. Briefly summarize what happened in the story so far.)
    
    IMPORTANT:
    - Include only factual information, preferences, events, activities, stories, conversational topics, personal details etc. that came up in the conversation.
    - Do NOT include pleasantries, greetings, or meta-conversation details.    
    - Return ONLY the JSON array of memories, nothing else.
    - Do NOT generate memories from the first system prompt, only from the conversation.

    Here is the conversation to extract memories from:
    {conversation_text}

    Review the list of existing memories below and only add new information or significantly different details. Do NOT create duplicate memories that convey the same information as existing memories:
    {existing_memories}
    """).strip()

    DEFAULT_MEMORY_FILE_PATH = "data/memories.json"
    
    def __init__(self, memory_file_path: str = DEFAULT_MEMORY_FILE_PATH):
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

    async def extract_and_store_conversation_memories(self, conversation: List[Dict[str, Any]]):
        """
        Extract memories from a conversation and store them in the memory file.
        
        Args:
            conversation (List[Dict[str, Any]]): The conversation history
        """
        memories = await self.extract_conversation_memories(conversation)
        
        if memories:
            await self.store_memories(memories)
            return True
        else:
            logging.warning("No memories were extracted from the conversation")
            return False

    async def extract_conversation_memories(self, conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract memories from a conversation.
        
        Args:
            conversation (List[Dict[str, Any]]): The conversation history
            
        Returns:
            List[Dict[str, Any]]: List of extracted memories
        """
        # Get existing memories to avoid duplicates
        existing_memories = self.get_memories_formatted()
        
        # Convert the conversation array to a formatted string
        conversation_text = ""
        for msg in conversation:
            role = msg.get('role', 'unknown')
            if role == 'user':
                role = 'companion'
            if role == 'assistant':
                role = 'phoenix'
            content = msg.get('content', '').replace('\n', ' ')
            conversation_text += f"{role.upper()}: {content}\n\n"

        # Create the combined prompt with conversation and existing memories
        combined_prompt = self.MEMORY_EXTRACTION_PROMPT_TEMPLATE.format(
            conversation_text=conversation_text,
            existing_memories=existing_memories
        )

        try:
            # Call OpenAI with the combined prompt as a single message
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "user", "content": combined_prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            # Get the response content and parse the JSON
            try:
                memories_text = response.choices[0].message.content                
                memories_data = json.loads(memories_text.strip())
                # Check if the response contains a memories array
                if isinstance(memories_data, dict):
                    if "memories" in memories_data:
                        memories = memories_data["memories"]
                    # Handle case where the response is a single memory object
                    elif all(key in memories_data for key in ["content", "topic", "importance"]):
                        memories = [memories_data]  # Wrap the single memory in a list
                    else:
                        logging.warning(f"Unexpected memories format: {memories_data}")
                        memories = []
                elif isinstance(memories_data, list):
                    memories = memories_data
                else:
                    logging.warning(f"Unexpected memories format: {memories_data}")
                    memories = []
                
                logging.info(f"Extracted {len(memories)} memories from conversation")
                return memories
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse memories JSON: {e}")
                logging.error(f"Raw response: {memories_text}")
                return []
                
        except Exception as e:
            logging.error(f"Error extracting memories from conversation: {e}")
            return []
        
    def _get_timestamp_data(self) -> tuple[str, str]:
        """
        Get the current timestamp data in both ISO and human-friendly formats.
        
        Returns:
            tuple: (iso_timestamp, friendly_date)
                - iso_timestamp: UTC timestamp in ISO format
                - friendly_date: Human-readable date and time in local timezone
        """
        # Get timezone-aware UTC time
        now = datetime.now(timezone.utc)
        iso_timestamp = now.isoformat()
        
        # Get local timezone name
        local_time = time.localtime()
        tz_name = time.tzname[local_time.tm_isdst]
        
        # Get local time in a friendly format
        local_now = datetime.fromtimestamp(time.time())
        friendly_date = local_now.strftime("%B %d, %Y at %I:%M %p") + f" {tz_name}"
        
        return iso_timestamp, friendly_date
        
    async def store_memories(self, memories: List[Dict[str, Any]]):
        """
        Store memories from a conversation.
        
        Args:
            memories (List[Dict[str, Any]]): List of memory objects from the conversation
        """
        current_memories = self._load_memories()
        
        # Get timestamp data for the memories
        iso_timestamp, friendly_date = self._get_timestamp_data()
        
        # Add timestamps to each memory
        for memory in memories:
            memory.update({
                "timestamp": iso_timestamp,
                "created_at": friendly_date
            })
            
        current_memories["memories"].extend(memories)
        self._save_memories(current_memories)
        logging.info(f"Stored {len(memories)} memories")
        
    def get_memories(self, 
                    start_time: Optional[str] = None,
                    end_time: Optional[str] = None,
                    limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve memories with optional filtering.
        
        Args:
            start_time (str, optional): ISO format datetime string to filter memories after this time
            end_time (str, optional): ISO format datetime string to filter memories before this time
            limit (int, optional): Maximum number of memories to return
            
        Returns:
            List[Dict[str, Any]]: List of matching memories
        """
        memories = self._load_memories()["memories"]
            
        if start_time:
            memories = [m for m in memories if m.get("timestamp", "") >= start_time]
            
        if end_time:
            memories = [m for m in memories if m.get("timestamp", "") <= end_time]
            
        # Sort by timestamp descending (newest last)
        memories.sort(key=lambda x: x.get("timestamp", ""), reverse=False)
        
        # Apply limit if specified
        if limit:
            memories = memories[:limit]
            
        return memories
        
    def get_memories_formatted(self, 
                          start_time: Optional[str] = None,
                          end_time: Optional[str] = None,
                          limit: Optional[int] = None) -> str:
        """
        Retrieve memories formatted as a markdown bullet list with relative timestamps.
        
        Args:
            start_time (str, optional): ISO format datetime string to filter memories after this time
            end_time (str, optional): ISO format datetime string to filter memories before this time
            limit (int, optional): Maximum number of memories to return
            
        Returns:
            str: Markdown formatted string with bullet list of memories
        """
        memories = self.get_memories(start_time, end_time, limit)
        
        if not memories:
            return "No memories yet."
        
        formatted_memories = []
        for memory in memories:
            relative_time = self._get_relative_time(memory.get("timestamp", ""))
            formatted_memories.append(f"* {relative_time}: {memory.get('content', '')}")
        
        return "\n".join(formatted_memories)
        
    def _get_relative_time(self, iso_timestamp: str) -> str:
        """
        Convert an ISO timestamp to a relative time string (e.g., "one minute ago").
        
        Args:
            iso_timestamp (str): ISO format datetime string
            
        Returns:
            str: Relative time as a human-readable string
        """
        if not iso_timestamp:
            return "Unknown time"
        
        try:
            # Parse the ISO timestamp
            timestamp = datetime.fromisoformat(iso_timestamp)
            
            # Get current time
            now = datetime.now(timezone.utc)
            
            # Calculate the time difference
            diff = now - timestamp
            seconds = diff.total_seconds()
            
            # Convert to appropriate units
            if seconds < 60:
                return "Just now"
            elif seconds < 3600:
                minutes = int(seconds / 60)
                return f"{'One minute' if minutes == 1 else f'{minutes} minutes'} ago"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{'One hour' if hours == 1 else f'{hours} hours'} ago"
            elif seconds < 604800:
                days = int(seconds / 86400)
                return f"{'One day' if days == 1 else f'{days} days'} ago"
            elif seconds < 2592000:
                weeks = int(seconds / 604800)
                return f"{'One week' if weeks == 1 else f'{weeks} weeks'} ago"
            elif seconds < 31536000:
                months = int(seconds / 2592000)
                return f"{'One month' if months == 1 else f'{months} months'} ago"
            else:
                years = int(seconds / 31536000)
                return f"{'One year' if years == 1 else f'{years} years'} ago"
        except (ValueError, TypeError):
            return "Unknown time"
        
    def clear_memories(self):
        """Clear all memories"""
        self._save_memories({"memories": []})
        logging.info("Cleared all memories") 
