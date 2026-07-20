"""
Open Web UI Knowledge Base API Client

Provides methods to interact with Open Web UI's knowledge base API:
- Upload files
- Wait for processing
- Add files to knowledge base
- Remove files from knowledge base
- List knowledge base files
"""

import logging
import mimetypes
import requests
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
from obsidian_ai_hub.utils import config as _hub_config
from .config import OPEN_WEB_UI_BASE_URL, OPEN_WEB_UI_API_KEY

logger = logging.getLogger(__name__)

# Timeout configurations
FILE_UPLOAD_TIMEOUT = 30  # seconds
FILE_PROCESS_TIMEOUT = 60  # seconds
FILE_PROCESS_POLL_INTERVAL = 2  # seconds
API_OPERATION_TIMEOUT = 10  # seconds


class WebUIClientError(Exception):
    """Base exception for Open Web UI client operations"""

    pass


def _guess_content_type(file_path: Path) -> str:
    """
    Guess a stable MIME type for uploads.

    Requests may omit the per-part Content-Type when only a file object is
    passed. Open WebUI's upload path is sensitive to this for text files.
    """
    content_type, _ = mimetypes.guess_type(file_path.name)
    return content_type or "text/plain"


def _response_detail(response: requests.Response) -> str:
    """Format a useful error message from an HTTP response."""
    detail = response.text.strip()
    if detail:
        return f"{response.status_code} {response.reason}: {detail}"
    return f"{response.status_code} {response.reason}"


def upload_file(file_path: Path) -> Optional[str]:
    """
    Upload a file to Open Web UI file storage.

    Args:
        file_path: Path to the file to upload

    Returns:
        file_id if successful, None if failed
    """
    _hub_config.ensure_external_allowed("Open Web UI file upload")
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return None

    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (
                    file_path.name,
                    f,
                    _guess_content_type(file_path),
                )
            }
            headers = {
                "Authorization": f"Bearer {OPEN_WEB_UI_API_KEY}",
            }

            url = f"{OPEN_WEB_UI_BASE_URL}/api/v1/files/"
            response = requests.post(
                url, headers=headers, files=files, timeout=FILE_UPLOAD_TIMEOUT
            )
            response.raise_for_status()

            file_id = response.json().get("id")
            logger.info(f"File uploaded: {file_path.name} (ID: {file_id})")
            return file_id

    except requests.RequestException as e:
        logger.error(f"Failed to upload file {file_path.name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error uploading {file_path.name}: {e}")
        return None


def wait_for_file_processing(file_id: str) -> bool:
    """
    Wait for a file to be processed by Open Web UI.

    Args:
        file_id: ID of the file to wait for

    Returns:
        True if processing completed successfully, False otherwise
    """
    _hub_config.ensure_external_allowed("Open Web UI file processing")
    start_time = time.time()

    try:
        headers = {
            "Authorization": f"Bearer {OPEN_WEB_UI_API_KEY}",
        }

        while True:
            # Check if timeout exceeded
            if time.time() - start_time > FILE_PROCESS_TIMEOUT:
                logger.error(f"File processing timeout for file_id: {file_id}")
                return False

            try:
                url = f"{OPEN_WEB_UI_BASE_URL}/api/v1/files/{file_id}/process/status"
                response = requests.get(
                    url, headers=headers, timeout=API_OPERATION_TIMEOUT
                )
                response.raise_for_status()

                status = response.json().get("status")
                logger.debug(f"File {file_id} processing status: {status}")

                if status == "completed":
                    logger.info(f"File {file_id} processing completed")
                    return True
                elif status == "failed":
                    logger.error(f"File {file_id} processing failed: {response.json()}")
                    return False

                # Wait before next poll
                time.sleep(FILE_PROCESS_POLL_INTERVAL)

            except requests.RequestException as e:
                logger.error(f"Error checking file processing status: {e}")
                # Continue polling despite temporary errors
                time.sleep(FILE_PROCESS_POLL_INTERVAL)

    except Exception as e:
        logger.error(f"Unexpected error waiting for file processing: {e}")
        return False


def add_to_knowledge(file_id: str, knowledge_id: str) -> bool:
    """
    Add a file to a knowledge base.

    Args:
        file_id: ID of the file to add
        knowledge_id: ID of the knowledge base

    Returns:
        True if successful, False otherwise
    """
    _hub_config.ensure_external_allowed("Open Web UI add to knowledge")
    try:
        headers = {
            "Authorization": f"Bearer {OPEN_WEB_UI_API_KEY}",
            "Content-Type": "application/json",
        }

        url = f"{OPEN_WEB_UI_BASE_URL}/api/v1/knowledge/{knowledge_id}/file/add"
        response = requests.post(
            url,
            headers=headers,
            json={"file_id": file_id},
            timeout=API_OPERATION_TIMEOUT,
        )
        response.raise_for_status()

        logger.info(f"File {file_id} added to knowledge base {knowledge_id}")
        return True

    except requests.RequestException as e:
        if getattr(e, "response", None) is not None:
            logger.error(
                f"Failed to add file to knowledge base: {_response_detail(e.response)}"
            )
        else:
            logger.error(f"Failed to add file to knowledge base: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error adding file to knowledge base: {e}")
        return False


def remove_from_knowledge(file_id: str, knowledge_id: str) -> bool:
    """
    Remove a file from a knowledge base.

    Args:
        file_id: ID of the file to remove
        knowledge_id: ID of the knowledge base

    Returns:
        True if successful, False otherwise
    """
    _hub_config.ensure_external_allowed("Open Web UI remove from knowledge")
    try:
        headers = {
            "Authorization": f"Bearer {OPEN_WEB_UI_API_KEY}",
            "Content-Type": "application/json",
        }

        url = f"{OPEN_WEB_UI_BASE_URL}/api/v1/knowledge/{knowledge_id}/file/remove"
        response = requests.post(
            url,
            headers=headers,
            json={"file_id": file_id},
            timeout=API_OPERATION_TIMEOUT,
        )
        response.raise_for_status()

        logger.info(f"File {file_id} removed from knowledge base {knowledge_id}")
        return True

    except requests.RequestException as e:
        if getattr(e, "response", None) is not None:
            logger.error(
                f"Failed to remove file from knowledge base: {_response_detail(e.response)}"
            )
        else:
            logger.error(f"Failed to remove file from knowledge base: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error removing file from knowledge base: {e}")
        return False


def list_knowledge_files(knowledge_id: str) -> Optional[List[Dict[str, Any]]]:
    """
    List all files in a knowledge base.

    Args:
        knowledge_id: ID of the knowledge base

    Returns:
        List of file information dicts, None if failed
    """
    _hub_config.ensure_external_allowed("Open Web UI list knowledge files")
    try:
        headers = {
            "Authorization": f"Bearer {OPEN_WEB_UI_API_KEY}",
        }

        url = f"{OPEN_WEB_UI_BASE_URL}/api/v1/knowledge/{knowledge_id}/files"
        response = requests.get(
            url, headers=headers, params={"page": 1}, timeout=API_OPERATION_TIMEOUT
        )
        response.raise_for_status()

        files = response.json().get("files", [])
        logger.debug(f"Retrieved {len(files)} files from knowledge base {knowledge_id}")
        return files

    except requests.RequestException as e:
        if getattr(e, "response", None) is not None:
            logger.error(
                f"Failed to list knowledge base files: {_response_detail(e.response)}"
            )
        else:
            logger.error(f"Failed to list knowledge base files: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error listing knowledge base files: {e}")
        return None
