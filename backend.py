# This file is part of Claude Plus.
#
# Claude Plus is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# at your option any later version.
#
# Claude Plus is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Claude Plus.  If not, see <https://www.gnu.org/licenses/>.
import os
import logging
import asyncio
from typing import Optional, List, Callable
from contextlib import asynccontextmanager
from functools import wraps
import subprocess
import platform
import shutil
import tempfile
from pathlib import Path
from starlette.background import BackgroundTask
import uvicorn
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from automode_logic import AutomodeRequest, start_automode_logic, automode_messages, automode_progress
from tools import tools, execute_tool 
from project_state import (
    sync_project_state_with_fs, clear_state_file, refresh_project_state,
    initialize_project_state, project_state, save_state_to_file
)
from config import PROJECTS_DIR, UPLOADS_DIR, CLAUDE_MODEL, anthropic_client
from shared_utils import (
    system_prompt, perform_search, encode_image_to_base64, create_folder, create_file,
    read_file, list_files, delete_file, write_to_file, get_safe_path
)

load_dotenv()


# app = FastAPI(lifespan=lifespan, docs_url="/docs", redoc_url="/redoc")

api_router = APIRouter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await initialize_project_state()
    await sync_project_state_with_fs()
    logger.info("Project state synchronized with file system")
    logger.info("Available endpoints:")
    for route in app.routes:
        if hasattr(route, "methods"):
            for method in route.methods:
                logger.info(f"{method} {route.path}")
    yield
    # Shutdown

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SSEMessage(BaseModel):
    event: str
    data: str
    
# Pydantic models
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    image: Optional[str] = None

class SearchQuery(BaseModel):
    query: str

class ProjectRequest(BaseModel):
    template: str
    
class CreateFileRequest(BaseModel):
    path: str
    content: str = ""

class FilePath(BaseModel):
    path: str
    content: Optional[str] = None

class CommandRequest(BaseModel):
    command: str

class DirectoryContents(BaseModel):
    path: str
    contents: List[str]

# Conversation history
conversation_history = []
    
@app.get("/")
async def root():
    return {"message": "Claude Plus backend is running!"}

@app.post("/automode")
async def start_automode(request: Request):
    automode_request = AutomodeRequest(**request.json())
    sync_project_state_with_fs()  # Ensure state is synced before starting
    return StreamingResponse(start_automode_logic(automode_request), media_type="text/event-stream")

@app.get("/automode")
async def start_automode_get(message: str):
    automode_request = AutomodeRequest(message=message)
    sync_project_state_with_fs()  # Ensure state is synced before starting
    return StreamingResponse(start_automode_logic(automode_request), media_type="text/event-stream")

@app.get("/automode-status")
async def get_automode_status():
    return {"progress": automode_progress, "messages": automode_messages}


def is_safe_path(path: str) -> bool:
    abs_projects_dir = os.path.abspath(PROJECTS_DIR)
    abs_path = os.path.abspath(os.path.join(PROJECTS_DIR, path))
    return os.path.commonpath([abs_projects_dir, abs_path]) == abs_projects_dir

def safe_path_operation(func: Callable):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        path = kwargs.get('path', '.')
        full_path = os.path.abspath(os.path.join(PROJECTS_DIR, path))
        print(f"[DEBUG] safe_path_operation: original_path={path}, full_path={full_path}")
        if not full_path.startswith(PROJECTS_DIR):
            raise HTTPException(status_code=403, detail="Access to this directory is not allowed")
        
        kwargs['path'] = os.path.relpath(full_path, PROJECTS_DIR)
        print(f"[DEBUG] safe_path_operation: adjusted_path={kwargs['path']}")
        return func(*args, **kwargs)
    return wrapper

@app.post("/create_project")
async def create_project(request: ProjectRequest, path: str):
    try:
        # Create project directory
        project_name = f"{request.template.lower()}_project"
        project_path = str(get_safe_path(path) / project_name)
        os.makedirs(project_path, exist_ok=True)

        # Handle different project templates
        if request.template == "react":
            await create_file(os.path.join(project_path, "package.json"), '{"name": "react-app", "version": "1.0.0"}')
            await create_file(
                os.path.join(project_path, "src/App.js"),
                'import React from "react";\n\nfunction App() {\n  return <div>Hello, React!</div>;\n}\n\nexport default App;'
            )
        elif request.template == "node":
            await create_file(os.path.join(project_path, "package.json"), '{"name": "node-app", "version": "1.0.0"}')
            await create_file(os.path.join(project_path, "index.js"), 'console.log("Hello, Node.js!");')
        elif request.template == "python":
            await create_file(os.path.join(project_path, "main.py"), 'print("Hello, Python!")')
            await create_file(os.path.join(project_path, "requirements.txt"), '')
        else:
            raise ValueError(f"Unknown project template: {request.template}")

        # Normalize the project path for the response
        relative_path = os.path.relpath(project_path, PROJECTS_DIR).replace("\\", "/")
        return {"message": f"{request.template} project created successfully at {relative_path}"}

    except Exception as e:
        logger.error(f"Error creating project: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating project: {str(e)}")

@app.post("/create_folder")
async def create_folder_endpoint(path: str = Query(...)):
    try:
        result = await create_folder(path)
        logger.info(f"Folder created: {path}")
        return {"message": result}
    except Exception as e:
        logger.error(f"Error creating folder: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create_file")
async def create_file_endpoint(path: str = Query(...), content: str = ""):
    try:
        # Remove any leading slashes to ensure the path is relative
        cleaned_path = path.lstrip('/')
        result = await create_file(cleaned_path, content)
        logger.info(f"File created: {cleaned_path}")
        return {"message": result}
    except Exception as e:
        logger.error(f"Error creating file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/read_file")
async def read_file_endpoint(path: str = Query(...)):
    try:
        content = await read_file(path)
        logger.info(f"File read: {path}")
        return {"content": content}
    except Exception as e:
        logger.error(f"Error reading file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/write_file")
async def write_file_endpoint(request: Request, path: str = Query(...)):
    try:
        logger.debug(f"Received path: {path}")
        try:
            body = await request.json()
            logger.debug(f"Received body: {body}")
        except Exception as e:
            logger.error(f"Error parsing JSON body: {str(e)}")
            raise HTTPException(status_code=422, detail="Invalid JSON body")

        content = body.get("content", "")
        if not content:
            raise HTTPException(status_code=422, detail="Content is required")

        logger.debug(f"Path: {path}, Content: {content}")
        result = await write_to_file(path, content)
        if "Error" in result:
            raise HTTPException(status_code=500, detail=result)
        return JSONResponse(content={"message": result})
    except Exception as e:
        logger.error(f"Error in write_file_endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/list_files")
async def list_files_endpoint(path: str = Query(".")):
    try:
        files = await list_files(path)
        return {"files": files, "currentDirectory": path}
    except Exception as e:
        logger.error(f"Error listing files: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete_file")
async def delete_file_endpoint(path: str = Query(...)):
    try:
        result = await delete_file(path)
        logger.info(f"File deleted: {path}")
        return {"message": result}
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_path = os.path.join(UPLOADS_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Read the file contents
        with open(file_path, "r") as f:
            file_contents = f.read()
        
        return {
            "message": f"File {file.filename} uploaded successfully to uploads directory",
            "file_contents": file_contents
        }
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@app.post("/analyze_image")
async def analyze_image(file: UploadFile = File(...)):
    try:
        logger.debug(f"Received file: {file.filename}, content_type: {file.content_type}")
        contents = await file.read()
        logger.debug(f"File contents read, length: {len(contents)} bytes")

        encoded_image = await encode_image_to_base64(contents)
        
        if encoded_image.startswith("Error encoding image:"):
            raise ValueError(encoded_image)

        logger.debug(f"Image encoded, length: {len(encoded_image)}")

        analysis_result = anthropic_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=system_prompt,
            messages=[
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": encoded_image
                            }
                        },
                        {
                            "type": "text",
                            "text": "Analyze this image and describe what you see."
                        }
                    ]
                }
            ]
        )
        logger.debug("Analysis result received from Anthropic API")
        return {"analysis": analysis_result.content[0].text}
    except Exception as e:
        logger.error(f"Error analyzing image: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

@app.post("/search")
async def search(query: SearchQuery):
    try:
        results = await perform_search(query.query)
        logger.info(f"Search results: {results}")
        return JSONResponse(content={"results": results})
    except Exception as e:
        logger.error(f"Error performing search: {str(e)}", exc_info=True)
        error_details = f"{type(e).__name__}: {str(e)}"
        if hasattr(e, '__traceback__'):
            import traceback
            error_details += f"\nTraceback:\n{''.join(traceback.format_tb(e.__traceback__))}"
        raise HTTPException(status_code=500, detail=f"Error performing search: {error_details}")

@app.post("/clear_state")
async def clear_project_state():
    try:
        global project_state, conversation_history
        project_state = await clear_state_file()
        await sync_project_state_with_fs()
        conversation_history = []  # Clear the conversation history
        logger.info("Project state cleared and synced with file system")
        return {"message": "Project state and chat history cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing project state: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Chat endpoint
@app.post("/chat")
async def chat(request: ChatRequest):
    global conversation_history, project_state
    try:
        message = request.message
        conversation_history.append({"role": "user", "content": message})
        
        # Sync project state before each interaction
        project_state = await sync_project_state_with_fs()
        
        # Update system prompt with current project state
        current_system_prompt = f"{system_prompt}\n\nCurrent project state:\nFolders: {', '.join(project_state['folders'])}\nFiles: {', '.join(project_state['files'])}"
        
        logger.info(f"Sending message to AI: {message}")
        logger.debug(f"Current project state before AI response: {project_state}")
        
        # Use asyncio.to_thread to run the synchronous method in a separate thread
        response = await asyncio.to_thread(
            anthropic_client.messages.create,
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=current_system_prompt,
            messages=conversation_history,
            tools=tools
        )
        
        logger.info(f"AI response: {response.content}")
        
        response_content = ""
        task_complete = False
        for content in response.content:
            if content.type == 'text':
                logger.info(f"Text response: {content.text}")
                response_content += content.text
            elif content.type == 'tool_use':
                tool_name = content.name
                tool_input = content.input
                logger.info(f"Tool used: {tool_name}, Input: {tool_input}")
                tool_result = await execute_tool(tool_name, tool_input)
                if tool_result['success']:
                    response_content += f"\nTool used: {tool_name}\nTool result: {tool_result['result']}\n"
                else:
                    response_content += f"\nTool used: {tool_name}\nTool error: {tool_result['error']}\n"
                logger.info(f"Tool result: {tool_result}")
            elif content.type == 'task_complete':
                task_complete = True

        if task_complete:
            response_content += "\nTask complete."

        conversation_history.append({"role": "assistant", "content": response_content})
        
        # Sync project state after AI response
        project_state = await sync_project_state_with_fs()
        logger.debug(f"Current project state after AI response: {project_state}")
        
        return {"response": response_content}
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@api_router.get("/download_projects")
async def download_projects():
    if not os.path.exists(PROJECTS_DIR):
        raise HTTPException(status_code=404, detail="Projects directory not found")

    temp_dir = tempfile.mkdtemp()
    try:
        zip_filename = "projects.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        
        shutil.make_archive(zip_path[:-4], 'zip', PROJECTS_DIR)
        
        return FileResponse(
            path=zip_path,
            filename=zip_filename,
            media_type='application/zip',
            background=BackgroundTask(cleanup, temp_dir)
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Error creating zip file: {str(e)}")

async def cleanup(temp_dir: str):
    shutil.rmtree(temp_dir, ignore_errors=True)

current_working_directory = PROJECTS_DIR

async def get_relative_cwd():
    global current_working_directory
    return str(Path(current_working_directory).relative_to(PROJECTS_DIR))

@api_router.get("/console/cwd")
async def console_get_current_working_directory():
    return {"cwd": await get_relative_cwd()}

async def execute_shell_command(command, cwd):
    shell = await get_shell()
    full_cwd = str(get_safe_path(cwd))
    if platform.system() == "Windows":
        result = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=full_cwd,
            shell=True
        )
    else:
        result = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=full_cwd
        )
    stdout, stderr = await result.communicate()
    return (stdout.decode() + stderr.decode()).strip()

async def get_shell():
    return "cmd.exe" if platform.system() == "Windows" else "/bin/bash"

@api_router.post("/console/execute")
async def console_execute_command(request: CommandRequest):
    global current_working_directory
    try:
        command_parts = request.command.split()
        cmd = command_parts[0].lower()

        if cmd == "cd":
            return await handle_cd(command_parts[1] if len(command_parts) > 1 else ".")
        elif cmd == "ls" or (cmd == "dir" and platform.system() == "Windows"):
            return await handle_ls(current_working_directory)
        elif cmd == "pwd":
            return await handle_pwd(current_working_directory)
        elif cmd == "echo":
            return await handle_echo(command_parts[1:], current_working_directory)
        elif cmd == "cat" or cmd == "type":
            return await handle_cat(command_parts[1] if len(command_parts) > 1 else "", current_working_directory)
        elif cmd == "mkdir":
            return await handle_mkdir(command_parts[1] if len(command_parts) > 1 else "", current_working_directory)
        elif cmd == "touch" or cmd == "echo.":
            return await handle_touch(command_parts[1] if len(command_parts) > 1 else "", current_working_directory)
        else:
            output = await execute_shell_command(request.command, current_working_directory)
            return {"result": output, "cwd": await get_relative_cwd()}
    except Exception as e:
        logger.error(f"Error in console_execute_command: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def handle_cd(path):
    global current_working_directory
    try:
        new_path = get_safe_path(os.path.join(current_working_directory, path))
        if new_path.is_dir():
            current_working_directory = str(new_path)
            return {"result": f"Changed directory to: {await get_relative_cwd()}", "cwd": await get_relative_cwd()}
        else:
            return {"result": f"Directory not found or access denied: {path}", "cwd": await get_relative_cwd()}
    except Exception as e:
        return {"result": f"Error changing directory: {str(e)}", "cwd": await get_relative_cwd()}

async def handle_ls(cwd):
    full_path = get_safe_path(cwd)
    items = os.listdir(full_path)
    return {"result": "\n".join(items), "cwd": await get_relative_cwd()}

async def handle_pwd(cwd):
    full_path = get_safe_path(cwd)
    return {"result": str(full_path), "cwd": await get_relative_cwd()}

async def handle_echo(args, cwd):
    return {"result": " ".join(args), "cwd": await get_relative_cwd()}

async def handle_cat(filename, cwd):
    try:
        full_path = get_safe_path(os.path.join(cwd, filename))
        with full_path.open('r') as file:
            content = file.read()
        return {"result": content, "cwd": await get_relative_cwd()}
    except Exception as e:
        return {"result": f"Error reading file: {str(e)}", "cwd": await get_relative_cwd()}

async def handle_mkdir(dirname, cwd):
    try:
        full_path = get_safe_path(os.path.join(cwd, dirname))
        full_path.mkdir(parents=True, exist_ok=True)
        return {"result": f"Directory created: {dirname}", "cwd": await get_relative_cwd()}
    except Exception as e:
        return {"result": f"Error creating directory: {str(e)}", "cwd": await get_relative_cwd()}

async def handle_touch(filename, cwd):
    try:
        full_path = get_safe_path(os.path.join(cwd, filename))
        full_path.touch()
        return {"result": f"File touched: {filename}", "cwd": await get_relative_cwd()}
    except Exception as e:
        return {"result": f"Error touching file: {str(e)}", "cwd": await get_relative_cwd()}


@api_router.post("/run_python")
async def run_python(request: CommandRequest):
    try:
        python_executable = shutil.which("python")
        if not python_executable:
            raise FileNotFoundError("Python executable not found")
        
        result = subprocess.run(
            [python_executable, "-c", request.command],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        output = result.stdout + result.stderr
        return {"result": output}
    except FileNotFoundError as e:
        logger.error(f"FileNotFoundError in run_python: {str(e)}", exc_info=True)
        return {"result": f"Error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error in run_python: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/pip_install")
async def pip_install(request: CommandRequest):
    try:
        result = subprocess.run(
            f"pip install {request.command}",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            executable=get_shell()
        )
        output = result.stdout.decode('utf-8') + result.stderr.decode('utf-8')
        return {"result": output}
    except subprocess.CalledProcessError as e:
        return {"result": f"Error: {e.stderr.decode('utf-8')}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/refresh_state")
async def refresh_project_state_endpoint():
    try:
        await refresh_project_state()
        logger.info("Project state refreshed successfully")
        return {"message": "Project state refreshed successfully"}
    except Exception as e:
        logger.error(f"Error refreshing project state: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
