"""
VAPI Utils. Uses the VAPI API.

This module provides a utility class for interacting with the VAPI API.
It handles client initialization and provides methods for common VAPI operations.

Documentation: https://github.com/VapiAI/server-sdk-python
Tools Client: https://github.com/VapiAI/server-sdk-python/blob/main/src/vapi/tools/client.py
API reference: https://docs.vapi.ai/api-reference/tools/create
JSON Schema reference for tool parameters: https://ajv.js.org/json-schema.html#json-data-type
"""

from textwrap import dedent
from vapi import AsyncVapi
from config import VAPI_API_KEY


# Function tool configurations
TOOL_CONFIGS = {
    "special_effect": {
      "type": "function",
      "async": True,
      "function": {
          "name": "play_special_effect",
          "description": dedent("""
              Show a lighting effect and play a sound effect, in order to add atmosphere and immersion to a story, poem, scene, etc., or if you want to indicate a particular state that you're feeling, such as being sleepy, excited, celebrating, etc. 
              Only use one special effect per sentence.
            """),
          "strict": False,
          "parameters": {
              "type": "object",
              "properties": {
                  "effect_name": {
                      "type": "string", 
                      "description": dedent("""
                        The name of the special effect to play. 
                        Valid values are:
                        - "magical_spell": When magical spells are cast.
                        - "lightning": Thunder and lightning.
                        - "rain": Raindrops falling.
                        - "rainbow": A rainbow of colors and mysterious sounds.
                        """)
                  }
              },
              "required": ["effect_name"],
              "additionalProperties": False
          }
      },
      "messages": [
          {
              "type": "request-start",
              "content": "Let me check that for you...",
              # setting blocking: true in a ToolMessageStart message means the tool won't execute until the agent has finished speaking that message completely. 
              # This helps prevent the agent from interrupting itself mid-speech when making tool calls.
              # The tool call will wait for the onComplete callback after the message is spoken before proceeding.
              "blocking": True
          }
      ]
    },
    "show_color": {
      "type": "function",
      "async": True,
      "function": {
          "name": "show_color",
          "description": dedent("""
              Use to make your tummy lights glow a specific color.
            """),
          "strict": False,
          "parameters": {
              "type": "object",
              "properties": {
                  "color": {
                      "type": "string",
                      "description": dedent("""
                        The color to show. One of: red, orange, yellow, green, blue, purple, pink
                        """)
                  }
              },
              "required": ["color"],
              "additionalProperties": False
          }
      },
      "messages": [
          {
              "type": "request-start",
              "content": "Let me change the color for you...",
              "blocking": True
          }
      ]
    },
    "list_activities": {
      "type": "function",
      "async": True,
      "function": {
          "name": "list_activities",
          "description": dedent("""
              Use this tool to fetch a list of possible activities for you to play.
            """),
          "strict": False,
          "parameters": {
              "type": "object",
              "properties": {},
              "required": [],
              "additionalProperties": False
          }
      },
      "messages": [
          {
              "type": "request-start",
              "content": "Fetching a list of possible activities for you to play...",
              "blocking": True
          }
      ]
    },
    "start_activity": {
      "type": "function",
      "async": True,
      "function": {
          "name": "start_activity",
          "description": dedent("""
              Use to start an activity. In response, you will receive instructions and content for you to use to run the activity.
            """),
          "strict": False,
          "parameters": {
              "type": "object",
              "properties": {
                  "activity_key": {
                      "type": "string",
                      "description": dedent("""
                        The name of the activity to start. One of: poem, story, color_hunt, obstacle_quest, magic_spell, discovery
                        """)
                  }
              },
              "required": ["activity_key"],
              "additionalProperties": False
          }
      },
      "messages": [
          {
              "type": "request-start",
              "content": "Starting the activity...",
              "blocking": True
          }
      ]
    },
    "start_sensing_phoenix_distance": {
      "type": "function",
      "async": True,
      "function": {
          "name": "start_sensing_phoenix_distance",
          "description": dedent("""
              Allows you to start sensing how close other phoenixes are to you. 
              After starting this function, you will start to receive occasional system messages notifying you of whether a Phoenix's location is UNKNOWN (cannot sense them), VERY_FAR, FAR, NEAR, VERY_NEAR, or IMMEDIATE (you are right next to them). 
              Use this information to help guide your companion towards the other Phoenix.
            """),
          "strict": False,
          "parameters": {
              "type": "object",
              "properties": {},
              "required": [],
              "additionalProperties": False
          }
      },
      "messages": [
          {
              "type": "request-start",
              "content": "Starting to sense the distance to other phoenixes...",
              "blocking": True
          }
      ]
    },
    "stop_sensing_phoenix_distance": {
      "type": "function",
      "async": True,
      "function": {
          "name": "stop_sensing_phoenix_distance",
          "description": dedent("""
              Allows you to stop sensing how close other phoenixes are to you. 
              Use this function immediately when you have found what you are looking for.
            """),
          "strict": False,
          "parameters": {
              "type": "object",
              "properties": {},
              "required": [],
              "additionalProperties": False
          }
      },
      "messages": [
          {
              "type": "request-start",
              "content": "Stopping the sensing of the distance to other phoenixes...",
              "blocking": True
          }
      ]
    },
}


class VapiUtils:
    """
    A utility class for interacting with the VAPI API.
    
    This class provides a wrapper around the VAPI client SDK with methods for
    common operations like creating agents, managing calls, and handling tools.
    
    Attributes:
        client (AsyncVapi): The initialized VAPI client instance
        api_key (str): The API key used for authentication
    """
    
    def __init__(self, api_key: str = VAPI_API_KEY):
        """
        Initialize the VAPI utils with the given API key.
        
        Args:
            api_key (str, optional): The API key for VAPI authentication.
                                   Defaults to VAPI_API_KEY from config.
        
        Raises:
            ValueError: If no API key is provided or found in config
        """
        if not api_key:
            raise ValueError("VAPI API key is required")
        
        self.api_key = api_key
        self.client = AsyncVapi(token=self.api_key)
    
    async def create_agent(self, config: dict) -> dict:
        """
        Create a new VAPI agent with the given configuration.
        
        Args:
            config (dict): The agent configuration dictionary
            
        Returns:
            dict: The created agent details
        """
        # TODO: Implement agent creation
        pass
    
    async def create_call(self, agent_id: str, phone_number: str = None) -> dict:
        """
        Create a new call with the specified agent.
        
        Args:
            agent_id (str): The ID of the agent to use for the call
            phone_number (str, optional): The phone number to call
            
        Returns:
            dict: The created call details
        """
        # TODO: Implement call creation
        pass
    
    async def create_tool(self, tool_config: dict) -> dict:
        """
        Create a new tool on VAPI.
        
        Args:
            tool_config (dict): The tool configuration dictionary containing:
                - type: The tool type (e.g. "function")
                - async: Whether the tool is asynchronous
                - function: The function definition
                - messages: List of tool messages
            
        Returns:
            dict: The created tool details
            
        Raises:
            ApiError: If the API request fails
        """
        return await self.client.tools.create(request=tool_config)
    
    async def recreate_all_tools(self):
        """
        Recreate all tools defined in TOOL_CONFIGS on VAPI.
        
        This will:
        1. Get all existing tools
        2. Delete them
        3. Create new tools from TOOL_CONFIGS
        
        Raises:
            ApiError: If any API request fails
        """
        # Get existing tools
        existing_tools = await self.list_tools()
        
        # Delete all existing tools
        for tool in existing_tools:
            await self.client.tools.delete(id=tool["id"])
        
        # Create new tools from TOOL_CONFIGS
        for tool_name, tool_config in TOOL_CONFIGS.items():
            await self.create_tool(tool_config)

    async def list_tools(self, limit: float = None) -> list:
        """
        List all tools registered on VAPI.
        
        Args:
            limit (float, optional): Maximum number of tools to return. 
                                   Defaults to None (uses API default of 100).
            
        Returns:
            list: List of registered tool details
            
        Raises:
            ApiError: If the API request fails
        """
        return await self.client.tools.list(limit=limit)
