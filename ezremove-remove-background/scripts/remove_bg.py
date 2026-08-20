#!/usr/bin/env python3
"""Create, poll, and optionally download an EzRemove background-removal job."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from config import get_api_base, get_api_key

SUCCESS, REQUEST_LIMIT, KEY_INVALID, INVALID_PARAMS, CREATE_FAILED = 100000, 400001, 400017, 400008, 400007
POLL_INTERVAL_SECONDS, CREATE_INTERVAL_SECONDS = 4, 3
MAX_BYTES = 20 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "AVIF"}
MODES = ("general_v2", "general_v1", "logo", "text", "anime", "custom")
OUTPUT_DIR_ENV_VARS = ("REMOVEBG_OUTPUT_DIR", "AGENT_OUTPUT_DIR")


class EzRemoveError(RuntimeError):
    """A safe, actionable error suitable for command-line output."""


def is_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def response_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def message_for(response: requests.Response, data: dict[str, Any]) -> str:
    message = data.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    if response.status_code == 429:
        return "The service rate-limited this request."
    return f"HTTP {response.status_code}" if response.status_code else "No response from the service"


def is_anonymous_daily_limit(data: dict[str, Any]) -> bool:
    """Recognize quota responses that must not be retried automatically."""
    if data.get("code") == 400006:
        return True
    message = data.get("message")
    text = message.lower() if isinstance(message, str) else ""
    return data.get("code") == REQUEST_LIMIT and any(
        phrase in text
        for phrase in ("daily limit", "daily quota", "free limit", "free quota", "anonymous limit")
    )


def api_error(action: str, response: requests.Response, data: dict[str, Any]) -> EzRemoveError:
    code, message = data.get("code"), message_for(response, data)
    if is_anonymous_daily_limit(data):
        return EzRemoveError(
            "The 10-per-day anonymous EzRemove allowance is exhausted. Do not retry this image. "
            "Create a Skill API key at https://ezremove.ai/settings/ and set EZ_REMOVE_API_KEY, then run it again."
        )
    if code == KEY_INVALID:
        return EzRemoveError("The EzRemove Skill API key is invalid or revoked. Create or copy a valid key from https://ezremove.ai/settings/ and set EZ_REMOVE_API_KEY.")
    if code == INVALID_PARAMS:
        return EzRemoveError(f"EzRemove rejected the input: {message}. Check the image, URL, and 20 MB limit.")
    if code in {400002, 400003}:
        return EzRemoveError("EzRemove requires an active login for this request. Sign in again at https://ezremove.ai/settings/.")
    if code == 400004:
        return EzRemoveError("The EzRemove job was not found or has expired. Submit the image again.")
    if code == 400005:
        return EzRemoveError("EzRemove cannot accept this request because the account has no credits. Add credits before trying again.")
    if code == CREATE_FAILED:
        return EzRemoveError(f"EzRemove could not create the job: {message}. Wait a moment and submit it again.")
    if response.status_code == 429 or code == REQUEST_LIMIT:
        return EzRemoveError("EzRemove is rate-limiting requests. Wait at least three seconds, then try again.")
    return EzRemoveError(f"EzRemove {action} failed (code={code!r}): {message}")


def auth_headers(api_key: Optional[str]) -> dict[str, str]:
    return {"X-Skill-API-Key": api_key} if api_key else {}


@contextmanager
def create_interval() -> Iterator[None]:
    """Serialize local job-creation requests."""
    cache_dir = Path(tempfile.gettempdir()) / "ezremove-skill"
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_path, lock_path = cache_dir / "skill-create.json", cache_dir / "skill-create.lock"
    with lock_path.open("a+") as lock_file:
        try:
            import fcntl  # POSIX hosts, including macOS and Linux agents.
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows fallback is process-local.
            fcntl = None
        try:
            try:
                previous = json.loads(state_path.read_text(encoding="utf-8")).get("created_at", 0)
            except (OSError, ValueError, AttributeError):
                previous = 0
            wait = CREATE_INTERVAL_SECONDS - (time.time() - float(previous))
            if wait > 0:
                time.sleep(wait)
            yield
            state_path.write_text(json.dumps({"created_at": time.time()}), encoding="utf-8")
        finally:
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def download_source_url(session: requests.Session, url: str) -> Path:
    """Download a public URL to a bounded temporary file for file-only upload."""
    temporary: Optional[Path] = None
    try:
        response = session.get(url, stream=True, timeout=90)
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_BYTES:
            raise EzRemoveError("The URL image exceeds the 20 MB limit. Use a smaller image.")
        fd, name = tempfile.mkstemp(prefix="ezremove-source-", suffix=".img")
        temporary = Path(name)
        total = 0
        with os.fdopen(fd, "wb") as destination:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise EzRemoveError("The URL image exceeds the 20 MB limit. Use a smaller image.")
                    destination.write(chunk)
        return temporary
    except (EzRemoveError, OSError, ValueError, requests.RequestException) as exc:
        if temporary:
            temporary.unlink(missing_ok=True)
        if isinstance(exc, EzRemoveError):
            raise
        raise EzRemoveError(f"Could not download the image URL: {exc}") from exc


def prepare_local_image(path: Path) -> tuple[Path, Optional[Path]]:
    if not path.is_file():
        raise EzRemoveError(f"Input file does not exist: {path}")
    if path.stat().st_size > MAX_BYTES:
        raise EzRemoveError("Input image exceeds the 20 MB limit. Compress it before submitting.")
    try:
        with Image.open(path) as image:
            if image.format not in SUPPORTED_FORMATS:
                raise EzRemoveError("Input must be JPG, JPEG, PNG, WebP, or AVIF. GIF is not supported.")
            image.verify()
        # The Skill API reduces images over 2500 px before inference. Preserve
        # the original upload here: smaller images are never enlarged.
        return path, None
    except (OSError, ValueError) as exc:
        raise EzRemoveError(f"Could not read input as a supported image: {exc}") from exc


def create_job(session: requests.Session, base_url: str, source: str, mode: str, custom_prompt: Optional[str], api_key: Optional[str]) -> str:
    downloaded: Optional[Path] = None
    temporary: Optional[Path] = None
    try:
        downloaded = download_source_url(session, source) if is_url(source) else None
        local_path = downloaded or Path(source).expanduser()
        prepared, temporary = prepare_local_image(local_path)
        for attempt in range(2):
            try:
                with prepared.open("rb") as image_file:
                    fields = {"mode": mode}
                    if custom_prompt:
                        fields["params"] = json.dumps({"prompt": custom_prompt})
                    response = session.post(f"{base_url}/api/ez-remove/skill/v1/remove-background", headers=auth_headers(api_key), files={"image_file": (prepared.name, image_file)}, data=fields, timeout=90)
            except requests.RequestException as exc:
                raise EzRemoveError(f"Could not create the EzRemove job: {exc}. The job may not have been submitted; retry once manually.") from exc
            data = response_json(response)
            is_rate_limit = response.status_code == 429 or data.get("code") == REQUEST_LIMIT
            if is_rate_limit and not is_anonymous_daily_limit(data) and attempt == 0:
                time.sleep(CREATE_INTERVAL_SECONDS)
                continue
            if data.get("code") != SUCCESS:
                raise api_error("job creation", response, data)
            job_id = (data.get("result") or {}).get("job_id")
            if isinstance(job_id, str) and job_id:
                return job_id
            raise EzRemoveError("EzRemove accepted the request but did not return a job ID. Retry once manually.")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
        if downloaded:
            downloaded.unlink(missing_ok=True)


def poll_job(session: requests.Session, base_url: str, job_id: str, api_key: Optional[str], timeout: int, interval: int) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = session.get(f"{base_url}/api/ez-remove/skill/v1/remove-background/{job_id}", headers=auth_headers(api_key), timeout=30)
        except requests.RequestException as exc:
            raise EzRemoveError(f"Could not check EzRemove job {job_id}: {exc}. Retry later.") from exc
        data = response_json(response)
        if data.get("code") not in {SUCCESS, 100001}:
            raise api_error("job lookup", response, data)
        if data.get("code") == 100001:
            time.sleep(interval)
            continue
        result, status = data.get("result") or {}, (data.get("result") or {}).get("status")
        if status == 2:
            preview = (result.get("output") or {}).get("preview") or []
            if preview and isinstance(preview[0], str):
                return preview[0]
            raise EzRemoveError("EzRemove completed the job but returned no preview PNG URL.")
        if status == 3:
            raise EzRemoveError(f"EzRemove could not process this image: {result.get('error') or 'unknown job error'}. Retry with a different image.")
        if status == 4:
            raise EzRemoveError(f"EzRemove blocked this image during content review: {result.get('error') or 'NSFW content'}. Use a different image.")
        if status not in {0, 1}:
            raise EzRemoveError(f"EzRemove returned an unknown job status: {status!r}.")
        time.sleep(interval)
    raise EzRemoveError(f"Timed out after {timeout} seconds waiting for job {job_id}. Retry later.")


def download_result(session: requests.Session, url: str, output: Path) -> Path:
    try:
        response = session.get(url, stream=True, timeout=90)
        response.raise_for_status()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as destination:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    destination.write(chunk)
    except (OSError, requests.RequestException) as exc:
        raise EzRemoveError(f"Background removal succeeded, but could not download the PNG to {output}: {exc}") from exc
    return output.resolve()


def default_output_path(source: str, job_id: str, output_dir: Optional[Path] = None) -> Optional[Path]:
    """Choose a portable output destination without assuming an agent vendor."""
    if output_dir:
        directory = output_dir.expanduser()
    else:
        configured = next((os.environ[name].strip() for name in OUTPUT_DIR_ENV_VARS if os.environ.get(name, "").strip()), None)
        if configured:
            directory = Path(configured).expanduser()
        elif is_url(source):
            return None
        else:
            directory = Path(source).expanduser().resolve().parent / "ezremove_output"

    name = Path(urlparse(source).path).stem if is_url(source) else Path(source).stem
    return directory / f"{name or job_id}-transparent.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="A local image path or public http(s) image URL")
    parser.add_argument("--mode", choices=MODES, default="general_v2", help="Removal model (default: general_v2)")
    parser.add_argument("--custom-prompt", help="Required description of the area to retain when --mode custom")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path, help="Path to save the transparent PNG")
    destination.add_argument("--output-dir", type=Path, help="Directory for the generated transparent PNG")
    parser.add_argument("--timeout", type=int, default=360, help="Maximum polling time in seconds (default: 360)")
    parser.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SECONDS, help="Polling interval in seconds, 3-5 (default: 4)")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if not 3 <= args.poll_interval <= 5:
        parser.error("--poll-interval must be between 3 and 5 seconds")
    if args.mode == "custom" and not args.custom_prompt:
        parser.error("--custom-prompt is required when --mode custom")
    if args.mode != "custom" and args.custom_prompt:
        parser.error("--custom-prompt can only be used when --mode custom")
    return args


def main() -> int:
    args = parse_args()
    api_key, base_url = get_api_key(), get_api_base()
    with requests.Session() as session:
        with create_interval():
            job_id = create_job(session, base_url, args.input, args.mode, args.custom_prompt, api_key)
        result_url = poll_job(session, base_url, job_id, api_key, args.timeout, args.poll_interval)
        result: dict[str, str] = {"job_id": job_id, "result_url": result_url}
        output = args.output or default_output_path(args.input, job_id, args.output_dir)
        if output:
            result["output"] = str(download_result(session, result_url, output))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EzRemoveError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
