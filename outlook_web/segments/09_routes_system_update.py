from __future__ import annotations

import http.client
import json
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from urllib.parse import quote, urlencode

if TYPE_CHECKING:
    from web_outlook_app import *  # noqa: F403


DOCKER_UPDATE_STATE_FILE_NAME = 'docker_update_state.json'
DOCKER_UPDATE_STATE_LOCK = threading.Lock()
DEFAULT_DOCKER_UPDATE_STATE: Dict[str, Any] = {
    'running': False,
    'started_at': None,
    'finished_at': None,
    'success': None,
    'message': '',
    'error': '',
    'container_id': '',
    'log_excerpt': '',
}
DOCKER_UPDATE_STATE: Dict[str, Any] = dict(DEFAULT_DOCKER_UPDATE_STATE)


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _docker_update_api_version() -> str:
    version = os.getenv('DOCKER_UPDATE_API_VERSION', 'v1.41').strip()
    return version if version.startswith('v') else f'v{version}'


def _docker_update_socket_path() -> str:
    return os.getenv('DOCKER_UPDATE_SOCKET', '/var/run/docker.sock').strip() or '/var/run/docker.sock'


def _docker_update_container_name() -> str:
    configured = os.getenv('DOCKER_UPDATE_CONTAINER', '').strip()
    if configured:
        return configured
    hostname = os.getenv('HOSTNAME', '').strip()
    return hostname or ''


def _docker_update_watchtower_image() -> str:
    return os.getenv('DOCKER_UPDATE_WATCHTOWER_IMAGE', 'containrrr/watchtower:latest').strip() or 'containrrr/watchtower:latest'


def _docker_update_timeout_seconds() -> int:
    try:
        timeout = int(os.getenv('DOCKER_UPDATE_TIMEOUT', '300'))
    except ValueError:
        timeout = 300
    return min(max(timeout, 30), 1800)


def _docker_update_status_timeout_seconds() -> int:
    try:
        timeout = int(os.getenv('DOCKER_UPDATE_STATUS_TIMEOUT', '10'))
    except ValueError:
        timeout = 10
    return min(max(timeout, 2), 120)


def _docker_update_state_file_path() -> str:
    override = os.getenv('DOCKER_UPDATE_STATE_FILE', '').strip()
    if override:
        target_path = os.path.abspath(override)
    else:
        database_path = os.path.abspath(str(DATABASE or ''))
        data_dir = os.path.dirname(database_path) if database_path else str(runtime_root())
        target_path = os.path.join(data_dir, DOCKER_UPDATE_STATE_FILE_NAME)

    parent_dir = os.path.dirname(target_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    return target_path


def _persist_docker_update_state(state: Dict[str, Any]) -> None:
    target_path = _docker_update_state_file_path()
    temp_path = f'{target_path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)
    os.replace(temp_path, target_path)


def _load_persisted_docker_update_state() -> Dict[str, Any]:
    target_path = _docker_update_state_file_path()
    if not os.path.exists(target_path):
        return dict(DEFAULT_DOCKER_UPDATE_STATE)

    try:
        with open(target_path, 'r', encoding='utf-8') as state_file:
            payload = json.load(state_file)
    except Exception:
        return dict(DEFAULT_DOCKER_UPDATE_STATE)

    if not isinstance(payload, dict):
        return dict(DEFAULT_DOCKER_UPDATE_STATE)

    restored_state = dict(DEFAULT_DOCKER_UPDATE_STATE)
    for key in DEFAULT_DOCKER_UPDATE_STATE:
        if key in payload:
            restored_state[key] = payload[key]

    # If the process restarted mid-update, convert the stale in-memory "running"
    # state into an unknown final result so the UI can prompt for a manual refresh.
    if restored_state.get('running'):
        restored_state.update({
            'running': False,
            'success': None,
            'finished_at': restored_state.get('finished_at') or datetime.now(timezone.utc).isoformat(),
            'message': 'Docker update status is unknown. The service may have restarted.',
            'error': '',
        })

    return restored_state


def get_docker_update_config() -> Dict[str, Any]:
    socket_path = _docker_update_socket_path()
    socket_supported = hasattr(socket, 'AF_UNIX')
    socket_exists = socket_supported and os.path.exists(socket_path)
    enabled = _env_flag('DOCKER_UPDATE_ENABLED', False)
    container_name = _docker_update_container_name()
    reason = ''
    current_image = ''
    if not enabled:
        reason = 'Docker update is disabled'
    elif not socket_supported:
        reason = 'Unix docker socket is not supported on this platform'
    elif not socket_exists:
        reason = f'Docker socket not found: {socket_path}'
    elif not container_name:
        reason = 'Docker update container name is empty'
    else:
        inspect_config = {
            'socket_path': socket_path,
            'api_version': _docker_update_api_version(),
            'timeout_seconds': _docker_update_status_timeout_seconds(),
        }
        try:
            container_info = _inspect_docker_container(inspect_config, container_name)
            container_name = _normalize_container_name(str(container_info.get('Name') or container_name))
            current_image = str((container_info.get('Config') or {}).get('Image') or '').strip()
            image_supported, image_reason = _docker_image_supports_online_update(current_image)
            if not image_supported:
                reason = image_reason
        except Exception as exc:
            reason = str(exc)

    return {
        'enabled': enabled,
        'available': enabled and socket_exists and bool(container_name) and not reason,
        'reason': reason,
        'socket_path': socket_path,
        'container': container_name,
        'current_image': current_image,
        'watchtower_image': _docker_update_watchtower_image(),
        'api_version': _docker_update_api_version(),
        'timeout_seconds': _docker_update_timeout_seconds(),
    }


def get_docker_update_state() -> Dict[str, Any]:
    with DOCKER_UPDATE_STATE_LOCK:
        return dict(DOCKER_UPDATE_STATE)


def _update_docker_update_state(**changes: Any) -> Dict[str, Any]:
    with DOCKER_UPDATE_STATE_LOCK:
        DOCKER_UPDATE_STATE.update(changes)
        state_snapshot = dict(DOCKER_UPDATE_STATE)
        _persist_docker_update_state(state_snapshot)
        return state_snapshot


with DOCKER_UPDATE_STATE_LOCK:
    DOCKER_UPDATE_STATE.update(_load_persisted_docker_update_state())


class _DockerUnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: int):
        super().__init__('localhost', timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


def _read_docker_api_body(response: http.client.HTTPResponse) -> str:
    return response.read().decode('utf-8', errors='replace')


def _docker_api_request(
    method: str,
    path: str,
    *,
    socket_path: str,
    api_version: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: int,
) -> Tuple[int, str]:
    request_body = None
    headers = {'Host': 'docker'}
    if body is not None:
        request_body = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
        headers['Content-Length'] = str(len(request_body))
    elif method.upper() in {'POST', 'PUT', 'PATCH'}:
        headers['Content-Length'] = '0'

    versioned_path = f'/{api_version}{path}'
    connection = _DockerUnixHTTPConnection(socket_path, timeout=timeout)
    try:
        connection.request(method, versioned_path, body=request_body, headers=headers)
        response = connection.getresponse()
        return response.status, _read_docker_api_body(response)
    finally:
        connection.close()


def _split_image_reference(image_ref: str) -> Tuple[str, str]:
    slash_index = image_ref.rfind('/')
    colon_index = image_ref.rfind(':')
    if colon_index > slash_index:
        return image_ref[:colon_index], image_ref[colon_index + 1:]
    return image_ref, 'latest'


def _normalize_container_name(name: str) -> str:
    return str(name or '').strip().lstrip('/')


def _inspect_docker_container(config: Dict[str, Any], container_ref: str) -> Dict[str, Any]:
    normalized_ref = str(container_ref or '').strip()
    if not normalized_ref:
        raise RuntimeError('Docker update container name is empty')

    status, body = _docker_api_request(
        'GET',
        f'/containers/{quote(normalized_ref, safe="")}/json',
        socket_path=config['socket_path'],
        api_version=config['api_version'],
        timeout=config['timeout_seconds'],
    )
    if status == 404:
        raise RuntimeError(f'Docker update target container not found: {normalized_ref}')
    if status < 200 or status >= 300:
        raise RuntimeError(f'Failed to inspect docker container: HTTP {status} {body}')

    try:
        payload = json.loads(body or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'Invalid docker inspect response: {body}') from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f'Invalid docker inspect response: {body}')
    return payload


def _docker_image_supports_online_update(image_ref: str) -> Tuple[bool, str]:
    normalized_ref = str(image_ref or '').strip()
    if not normalized_ref:
        return False, 'Docker update current image is empty'

    if '@' in normalized_ref:
        return False, f'Docker online update does not support digest-pinned images: {normalized_ref}'

    _repository, image_tag = _split_image_reference(normalized_ref)
    normalized_tag = str(image_tag or '').strip()
    if re.fullmatch(r'v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', normalized_tag):
        return False, (
            'Docker online update requires a mutable image tag like latest/main/dev; '
            f'current image is pinned to {normalized_ref}'
        )

    return True, ''


def build_watchtower_create_payload(
    *,
    container_name: str,
    socket_path: str,
    watchtower_image: str,
) -> Dict[str, Any]:
    return {
        'Image': watchtower_image,
        'Cmd': ['--run-once', '--cleanup', container_name],
        'Tty': True,
        'Env': [f'DOCKER_HOST=unix://{socket_path}'],
        'HostConfig': {
            'AutoRemove': True,
            'Binds': [f'{socket_path}:{socket_path}'],
        },
    }


def _docker_pull_stream_error(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        error_detail = payload.get('errorDetail')
        detail_message = ''
        if isinstance(error_detail, dict):
            detail_message = str(error_detail.get('message') or '').strip()

        error_message = str(payload.get('error') or '').strip()
        if error_message or detail_message:
            return error_message or detail_message

    return ''


def _docker_log_excerpt(body: str, max_lines: int = 12, max_chars: int = 2000) -> str:
    lines = [line.rstrip() for line in str(body or '').splitlines() if line.strip()]
    if not lines:
        return ''

    excerpt = '\n'.join(lines[-max_lines:])
    if len(excerpt) > max_chars:
        excerpt = excerpt[-max_chars:]
    return excerpt.strip()


def _read_watchtower_logs(config: Dict[str, Any], container_id: str) -> str:
    path = (
        f'/containers/{quote(container_id, safe="")}/logs?'
        + urlencode({
            'stdout': 1,
            'stderr': 1,
            'follow': 1,
            'timestamps': 0,
            'tail': 200,
        })
    )
    connection = _DockerUnixHTTPConnection(config['socket_path'], timeout=config['timeout_seconds'])
    try:
        connection.request('GET', f'/{config["api_version"]}{path}', headers={'Host': 'docker'})
        response = connection.getresponse()
        body = _read_docker_api_body(response)
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f'Failed to read watchtower logs: HTTP {response.status} {body}')
        return body
    finally:
        connection.close()


def _classify_watchtower_logs(logs: str, current_image: str) -> Tuple[Optional[bool], str]:
    normalized_logs = str(logs or '').lower()
    if not normalized_logs.strip():
        return None, ''

    if 'no new images found' in normalized_logs:
        return False, (
            'No new image found for the current tag. If you use latest/main/dev, '
            'wait for the registry image to finish publishing and retry.'
        )

    if 'no running containers to watch' in normalized_logs or 'no running containers to update' in normalized_logs:
        return False, 'Watchtower did not find a matching running target container.'

    if 'unable to update container' in normalized_logs or 'failed' in normalized_logs or 'error' in normalized_logs:
        return False, f'Watchtower reported an update failure for {current_image or "the current image"}.'

    return True, 'Docker image update completed. Service restart should begin shortly.'


def _ensure_watchtower_image(config: Dict[str, Any]) -> None:
    image_name, image_tag = _split_image_reference(config['watchtower_image'])
    query = urlencode({'fromImage': image_name, 'tag': image_tag})
    status, body = _docker_api_request(
        'POST',
        f'/images/create?{query}',
        socket_path=config['socket_path'],
        api_version=config['api_version'],
        timeout=config['timeout_seconds'],
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f'Failed to pull watchtower image: HTTP {status} {body}')
    stream_error = _docker_pull_stream_error(body)
    if stream_error:
        raise RuntimeError(f'Failed to pull watchtower image: {stream_error}')


def _create_watchtower_container(config: Dict[str, Any]) -> str:
    container_suffix = str(int(time.time()))
    container_name = f'outlookemail-watchtower-update-{container_suffix}'
    payload = build_watchtower_create_payload(
        container_name=config['container'],
        socket_path=config['socket_path'],
        watchtower_image=config['watchtower_image'],
    )
    status, body = _docker_api_request(
        'POST',
        f'/containers/create?{urlencode({"name": container_name})}',
        socket_path=config['socket_path'],
        api_version=config['api_version'],
        body=payload,
        timeout=config['timeout_seconds'],
    )
    if status not in {201, 202}:
        raise RuntimeError(f'Failed to create watchtower container: HTTP {status} {body}')

    try:
        payload_body = json.loads(body or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'Invalid docker create response: {body}') from exc

    container_id = str(payload_body.get('Id') or '').strip()
    if not container_id:
        raise RuntimeError(f'Docker create response did not include a container id: {body}')
    return container_id


def _start_watchtower_container(config: Dict[str, Any], container_id: str) -> None:
    status, body = _docker_api_request(
        'POST',
        f'/containers/{quote(container_id, safe="")}/start',
        socket_path=config['socket_path'],
        api_version=config['api_version'],
        timeout=config['timeout_seconds'],
    )
    if status not in {204, 304}:
        raise RuntimeError(f'Failed to start watchtower container: HTTP {status} {body}')


def run_docker_update_job(config: Dict[str, Any]) -> None:
    _update_docker_update_state(
        running=True,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        success=None,
        message='Pulling watchtower image',
        error='',
        container_id='',
        log_excerpt='',
    )
    try:
        _ensure_watchtower_image(config)
        _update_docker_update_state(message='Creating watchtower update container')
        container_id = _create_watchtower_container(config)
        _update_docker_update_state(
            message='Starting watchtower update container',
            container_id=container_id,
        )
        _start_watchtower_container(config, container_id)
        _update_docker_update_state(message='Watching update task output')
        logs = _read_watchtower_logs(config, container_id)
        excerpt = _docker_log_excerpt(logs)
        classified_success, classified_message = _classify_watchtower_logs(logs, str(config.get('current_image') or ''))
        if classified_success is False:
            _update_docker_update_state(
                running=False,
                finished_at=datetime.now(timezone.utc).isoformat(),
                success=False,
                message=classified_message,
                error=classified_message,
                container_id=container_id,
                log_excerpt=excerpt,
            )
            return
        if classified_success is True:
            _update_docker_update_state(
                running=False,
                finished_at=datetime.now(timezone.utc).isoformat(),
                success=True,
                message=classified_message,
                error='',
                container_id=container_id,
                log_excerpt=excerpt,
            )
            return
        _update_docker_update_state(
            running=False,
            finished_at=datetime.now(timezone.utc).isoformat(),
            success=True,
            message='Docker update task started. The service may restart shortly.',
            error='',
            container_id=container_id,
            log_excerpt=excerpt,
        )
    except Exception as exc:
        _update_docker_update_state(
            running=False,
            finished_at=datetime.now(timezone.utc).isoformat(),
            success=False,
            message='Docker update failed',
            error=str(exc),
            log_excerpt='',
        )


def start_docker_update_job(config: Dict[str, Any]) -> Tuple[bool, str]:
    with DOCKER_UPDATE_STATE_LOCK:
        if DOCKER_UPDATE_STATE.get('running'):
            return False, 'Docker update is already running'
        DOCKER_UPDATE_STATE.update({
            'running': True,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'finished_at': None,
            'success': None,
            'message': 'Docker update queued',
            'error': '',
            'container_id': '',
            'log_excerpt': '',
        })
        _persist_docker_update_state(dict(DOCKER_UPDATE_STATE))

    thread = threading.Thread(
        target=run_docker_update_job,
        args=(dict(config),),
        name='docker-update',
        daemon=True,
    )
    thread.start()
    return True, 'Docker update task queued'


@app.route('/api/docker-update/status', methods=['GET'])
@login_required
def api_get_docker_update_status():
    return jsonify({
        'success': True,
        'docker_update': {
            **get_docker_update_config(),
            'state': get_docker_update_state(),
        },
    })


@app.route('/api/docker-update', methods=['POST'])
@login_required
def api_start_docker_update():
    config = get_docker_update_config()
    if not config['enabled']:
        return jsonify({'success': False, 'error': config['reason']}), 403
    if not config['available']:
        return jsonify({'success': False, 'error': config['reason']}), 503

    started, message = start_docker_update_job(config)
    if not started:
        return jsonify({'success': False, 'error': message, 'docker_update': get_docker_update_state()}), 409

    return jsonify({
        'success': True,
        'message': message,
        'docker_update': {
            **config,
            'state': get_docker_update_state(),
        },
    }), 202
