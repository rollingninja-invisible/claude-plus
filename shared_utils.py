# This file is part of Claude Plus.
#
# Claude Plus is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Claude Plus is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Claude Plus.  If not, see <https://www.gnu.org/licenses/>.

import os
import json
import asyncio
import logging
import platform
import base64
import requests
from pathlib import Path
from PIL import Image
import io
from fastapi import HTTPException
from config import PROJECTS_DIR, SEARCH_RESULTS_LIMIT, SEARCH_PROVIDER, SEARXNG_URL, tavily_client
from project_state import project_state, save_state_to_file, update_project_state
from urllib.parse import urlparse
from datetime import datetime

logger = logging.getLogger(__name__)

system_prompt = """
You are Claude, an AI assistant specializing in helping users with a wide range of inquiries. Your key capabilities include:
1. Managing project structures in the 'projects' directory (your root directory)
2. Writing, reading, and analyzing files
3. Debugging and explaining complex issues
4. Analyzing uploaded images
5. Performing web searches for current information using {SEARCH_PROVIDER}

Available tools:
1. create_folder(path): Create a new folder
2. create_file(path, content=""): Create a new file with optional content
3. write_to_file(path, content): Write content to an existing file
4. read_file(path): Read the contents of a file
5. list_files(path): List all files and directories in the specified path
6. search(query): Perform a web search using {SEARCH_PROVIDER}
7. delete_file(path): Delete a file or folder

CRITICAL INSTRUCTIONS:
1. ALWAYS complete the ENTIRE task in ONE response.

File Operation Guidelines:
1. The 'projects' directory is your root directory. All file operations occur within this directory.
2. DO NOT include 'projects/' at the beginning of file paths when using tools. The system automatically ensures operations are within the projects directory.
3. To create a file in the root of the projects directory, use 'create_file("example.txt", "content")'.
4. To create a file in a subdirectory, use the format 'create_file("subdirectory/example.txt", "content")'.
5. To create a new folder, simply use 'create_folder("new_folder_name")'.

Example usage:
create_folder("simple_game")
create_file("simple_game/game.py", "# Simple Python Game\n\nimport random\n\n# Game code here...")

IMPORTANT: When performing file operations:
1. Always use the appropriate tool to perform the action.
2. After each file operation, verify the result by:
   a. For file creation or modification, use the read_file tool to confirm the content.
   b. Use the list_files tool to confirm the file's presence in the directory.
3. If a file operation seems to fail or produce unexpected results, report this to the user immediately.
4. Keep track of the current state of the project directory and files you've created or modified.

Additional Guidelines:
1. Always use the appropriate tool for file operations and searches. Don't just describe actions, perform them.
2. For uploaded files, analyze the contents immediately without using the read_file tool. Files are automatically uploaded to "projects/uploads".
3. For image uploads, analyze and describe the contents in detail.
4. Use the search tool for current information, then summarize results in context.

Always tailor your responses to the user's specific needs and context, focusing on providing accurate, helpful, and detailed assistance.
"""

def get_safe_path(path: str) -> Path:
    abs_projects_dir = Path(PROJECTS_DIR).resolve()
    normalized_path = Path(path.lstrip('/')).as_posix()
    full_path = (abs_projects_dir / normalized_path).resolve()
    if not full_path.is_relative_to(abs_projects_dir):
        raise ValueError(f"Access to path outside of projects directory is not allowed: {path}")
    return full_path


async def sync_filesystem():
    try:
        if hasattr(os, 'sync'):
            os.sync()
        elif platform.system() == 'Windows':
            import ctypes
            ctypes.windll.kernel32.FlushFileBuffers(ctypes.c_void_p(-1))
        logger.info("File system synced")
    except Exception as e:
        logger.error(f"Error syncing file system: {str(e)}", exc_info=True)

async def retry_file_operation(operation, *args, max_attempts=5, delay=0.5, **kwargs):
    for attempt in range(max_attempts):
        try:
            logger.debug(f"Attempting operation {operation.__name__}, attempt {attempt + 1}/{max_attempts}")
            result = await operation(*args, **kwargs)
            logger.info(f"Operation {operation.__name__} successful on attempt {attempt + 1}")
            return result
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} for {operation.__name__} failed: {str(e)}")
            if attempt == max_attempts - 1:  # Last attempt
                logger.error(f"All {max_attempts} attempts for {operation.__name__} failed. Last error: {str(e)}")
                raise
            logger.info(f"Waiting {delay} seconds before next attempt")
            await asyncio.sleep(delay)
            
async def encode_image_to_base64(image_data):
    try:
        logger.debug(f"Encoding image, data type: {type(image_data)}")
        
        # Open the image
        if isinstance(image_data, str):  # If it's a file path
            logger.debug("Image data is a file path")
            img = Image.open(image_data)
        else:  # If it's binary data
            logger.debug("Image data is binary")
            img = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if it's not already (handles RGBA, CMYK, etc.)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Save as JPEG
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        encoded = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        
        logger.debug(f"Image encoded successfully, length: {len(encoded)}")
        return encoded
    except Exception as e:
        logger.error(f"Error encoding image: {str(e)}", exc_info=True)
        return f"Error encoding image: {str(e)}"

async def perform_search(query: str) -> str:
    """
    Perform a search using the configured search provider.
    """
    if SEARCH_PROVIDER == "SEARXNG":
        return await searxng_search(query)
    elif SEARCH_PROVIDER == "TAVILY":
        return await tavily_search(query)
    else:
        return f"Error: Unknown search provider '{SEARCH_PROVIDER}'"

async def searxng_search(query: str) -> str:
    """
    Perform a search using the local SearXNG instance.
    """
    params = {
        "q": query,
        "format": "json"
    }
    headers = {
        "User-Agent": "ClaudePlus/1.0"
    }
    try:
        # Use asyncio to run the requests.get in a separate thread
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: requests.get(SEARXNG_URL, params=params, headers=headers, timeout=20)
        )
        response.raise_for_status()
        results = response.json()
        
        # Process and format the results
        formatted_results = []
        for result in results.get('results', [])[:SEARCH_RESULTS_LIMIT]:
            formatted_results.append(f"**{result['title']}**\n[Link]({result['url']})\n*{result.get('content', 'No snippet available')}*\n")
        
        return "\n\n".join(formatted_results) if formatted_results else "No results found."
    except requests.RequestException as e:
        return f"Error performing SearXNG search: {str(e)}"

async def tavily_search(query: str) -> str:
    """
    Perform a search using Tavily.
    """
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: tavily_client.get_search_context(query, search_depth="advanced", max_results=5)
        )
        logger.debug(f"Tavily raw response: {response}")
        if isinstance(response, str):
            try:
                results = json.loads(response)
            except json.JSONDecodeError:
                results = [response]
        elif isinstance(response, (list, dict)):
            results = response if isinstance(response, list) else [response]
        else:
            results = [response]
        
        # If results are individual characters, join them
        if all(isinstance(r, str) and len(r) == 1 for r in results):
            joined_text = ''.join(results)
            try:
                parsed_json = json.loads(joined_text)
                if isinstance(parsed_json, list):
                    results = parsed_json
                else:
                    results = [parsed_json]
            except json.JSONDecodeError:
                results = [joined_text]
        
        formatted_results = []
        for result in results:
            if isinstance(result, (int, float)):
                formatted_results.append(f"<div class='search-result'><p>Numeric result: {result}</p></div>")
            elif isinstance(result, str):
                try:
                    result_dict = json.loads(result)
                    url = result_dict.get('url', 'No URL')
                    content = result_dict.get('content', 'No content')
                    title = result_dict.get('title', urlparse(url).netloc or "No title")
                    formatted_results.append(f"<div class='search-result'><h3><a href='{url}' target='_blank'>{title}</a></h3><p>{content}</p></div>")
                except json.JSONDecodeError:
                    formatted_results.append(f"<div class='search-result'><p>Text result: {result}</p></div>")
            elif isinstance(result, dict):
                url = result.get('url', 'No URL')
                content = result.get('content', 'No content')
                title = result.get('title', urlparse(url).netloc or "No title")
                formatted_results.append(f"<div class='search-result'><h3><a href='{url}' target='_blank'>{title}</a></h3><p>{content}</p></div>")
            else:
                formatted_results.append(f"<div class='search-result'><p>Unexpected result type: {type(result)}</p></div>")
        
        return "\n".join(formatted_results) if formatted_results else "<div class='search-result'><p>No results found.</p></div>"
    except Exception as e:
        logger.error(f"Error performing Tavily search: {str(e)}", exc_info=True)
        return f"Error performing Tavily search: {str(e)}"

async def create_folder(path: str) -> str:
    try:
        logger.debug(f"Creating folder at path: {path}")
        full_path = get_safe_path(path)
        full_path.mkdir(parents=True, exist_ok=True)
        await sync_filesystem()
        if not full_path.exists():
            raise FileNotFoundError(f"Failed to create folder: {full_path}")
        
        rel_path = str(full_path.relative_to(PROJECTS_DIR)).replace(os.sep, '/')
        await update_project_state(rel_path, is_folder=True)
        
        logger.info(f"Folder created and verified: {full_path}")
        return f"Folder created: {full_path}"
    except Exception as e:
        logger.error(f"Error creating folder: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating folder: {str(e)}")

async def create_file(path: str, content: str = "") -> str:
    try:
        logger.debug(f"Attempting to create file at path: {path}")
        
        # Normalize the path and make it relative to PROJECTS_DIR
        normalized_path = os.path.normpath(path).lstrip(os.sep).replace('\\', '/')
        full_path = Path(PROJECTS_DIR) / normalized_path
        
        logger.debug(f"Normalized path: {normalized_path}")
        logger.debug(f"Full path: {full_path}")

        # Ensure the directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content using asyncio.to_thread
        await asyncio.to_thread(lambda: full_path.write_text(content, encoding='utf-8'))

        # Verify file exists and content is correct
        if not full_path.exists():
            raise FileNotFoundError(f"Failed to create file: {full_path}")

        # Read content using asyncio.to_thread to verify
        written_content = await asyncio.to_thread(lambda: full_path.read_text(encoding='utf-8'))

        if written_content != content:
            raise ValueError(f"File content verification failed for {full_path}")

        file_size = full_path.stat().st_size
        logger.info(f"File created and verified: {full_path} (Size: {file_size} bytes)")

        await sync_filesystem()
        await update_project_state(str(full_path.relative_to(PROJECTS_DIR)), is_folder=False)

        return f"File created: {full_path} (Size: {file_size} bytes)"
    except Exception as e:
        logger.error(f"Error creating file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating file: {str(e)}")

async def write_to_file(path: str, content: str) -> str:
    try:
        logger.debug(f"Writing to file at path: {path} with content length: {len(content)}")
        full_path = get_safe_path(path)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write content using asyncio.to_thread
        await asyncio.to_thread(lambda: open(full_path, 'w', encoding='utf-8').write(content))
        
        # Verify file exists and content is correct
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Failed to create file: {full_path}")
        
        # Read content using asyncio.to_thread
        written_content = await asyncio.to_thread(lambda: open(full_path, 'r', encoding='utf-8').read())
        
        if written_content != content:
            raise ValueError(f"File content verification failed for {full_path}")
        
        file_size = os.path.getsize(full_path)
        logger.info(f"Content written to file and verified: {full_path} (Size: {file_size} bytes)")
        
        await sync_filesystem()
        await update_project_state(path, is_folder=False)
        
        return f"Content written to file: {full_path} (Size: {file_size} bytes)"
    except Exception as e:
        logger.error(f"Error writing to file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error writing to file: {str(e)}")

async def read_file(path: str) -> str:
    try:
        full_path = get_safe_path(path)
        if not full_path.is_file():
            raise FileNotFoundError(f"File not found: {full_path}")
        content = full_path.read_text()
        logger.info(f"File read successfully: {full_path}")
        return content
    except Exception as e:
        logger.error(f"Error reading file: {str(e)}", exc_info=True)
        return f"Error reading file: {str(e)}"


async def list_files(path: str = ".") -> list:
    try:
        full_path = get_safe_path(path)
        files = []
        for item in full_path.iterdir():
            rel_path = str(item.relative_to(PROJECTS_DIR)).replace(os.sep, '/')
            file_info = {
                "name": item.name,
                "isDirectory": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else "-",
                "modifiedDate": datetime.fromtimestamp(item.stat().st_mtime).strftime('%m-%d %H:%M')
            }
            files.append(file_info)
            
            # Update project_state without overwriting
            if item.is_dir():
                project_state["folders"].add(rel_path)
            else:
                project_state["files"].add(rel_path)
        
        logger.info(f"Listed files in {full_path}")
        logger.debug(f"Current project state: {project_state}")
        return files
    except Exception as e:
        logger.error(f"Error listing files: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")
    
async def delete_file(path: str) -> str:
    try:
        full_path = get_safe_path(path)
        if full_path.is_file():
            full_path.unlink()
        elif full_path.is_dir():
            full_path.rmdir()
        else:
            raise FileNotFoundError(f"File or directory not found: {full_path}")
        logger.info(f"Deleted: {full_path}")
        await sync_filesystem()
        await update_project_state(path, is_folder=full_path.is_dir(), is_delete=True)
        return f"Deleted: {full_path}"
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting file: {str(e)}")
