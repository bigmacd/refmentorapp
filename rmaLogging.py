import logging
import os
import warnings


# Suppress websocket deprecation warnings BEFORE importing NiceGUI
warnings.filterwarnings('ignore', message='.*remove second argument of ws_handler.*', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*websockets.*legacy.*', category=DeprecationWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning, module='websockets.*')
warnings.filterwarnings('ignore', category=RuntimeWarning, module='websockets.*')

# Configure logging before importing NiceGUI
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Set NiceGUI and related loggers to the configured level
log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.getLogger('nicegui').setLevel(log_level)
logging.getLogger('uvicorn').setLevel(log_level)
logging.getLogger('uvicorn.access').setLevel(log_level)
logging.getLogger('uvicorn.error').setLevel(log_level)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


# By default we hide noisy Socket.IO / WebSocket stack traces. That also hides the *real* reason
# the browser shows "WebSocket connection ... failed". Set REFMENTOR_LOG_WEBSOCKETS=1 when debugging.
_SUPPRESS_WEBSOCKET_LOG_NOISE = not _env_truthy('REFMENTOR_LOG_WEBSOCKETS')
if not _SUPPRESS_WEBSOCKET_LOG_NOISE:
    logging.getLogger('rmaLogging').warning(
        'REFMENTOR_LOG_WEBSOCKETS is set: showing full WebSocket / Socket.IO / engineio logs'
    )

# Filter out non-critical drawer timeout errors
class DrawerTimeoutFilter(logging.Filter):
    def filter(self, record):
        # Suppress JavaScript timeout errors from drawer state checking
        if 'JavaScript did not respond' in record.getMessage():
            return False
        return True

# Filter out Socket.IO handshake errors (non-critical internal errors)
class SocketIOErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # Suppress Socket.IO handshake errors that are often non-critical
        # These are internal Socket.IO errors that don't affect functionality
        if '_on_handshake' in msg:
            return False
        if 'Task exception was never retrieved' in msg and 'socketio' in msg.lower():
            return False
        if 'missing 1 required positional argument' in msg and 'socketio' in str(record.pathname).lower():
            return False
        if 'remove second argument of ws_handler' in msg:
            return False
        if "'websocket.accept', 'websocket.close', or 'websocket.http.response.start'" in msg:
            return False
        return True


# Filter out WebSocket/EngineIO errors (non-critical NiceGUI internal errors)
class WebSocketErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        pathname_str = str(record.pathname).lower() if record.pathname else ''

        # Suppress websocket deprecation warnings
        if 'remove second argument of ws_handler' in msg:
            return False
        if 'websockets/legacy' in pathname_str:
            return False

        # Suppress websocket runtime errors from engineio/socketio/uvicorn
        if 'RuntimeError' in record.levelname:
            if any(x in pathname_str for x in ['websocket', 'engineio', 'socketio', 'uvicorn']):
                # These often happen on disconnect/reconnect and are handled internally
                return False
            if any(x in msg.lower() for x in ['websocket', 'asgi', 'http.response']):
                return False

        # Suppress websocket ASGI application exceptions
        if 'Exception in ASGI application' in msg:
            if any(x in pathname_str for x in ['websocket', 'engineio', 'socketio']):
                return False
            if 'websocket' in msg.lower() or 'engineio' in msg.lower():
                return False

        # Suppress uvicorn websocket protocol errors
        if 'uvicorn/protocols/websockets' in pathname_str:
            if 'RuntimeError' in record.levelname or 'ERROR' in record.levelname:
                return False

        # Suppress engineio ASGI driver errors
        if 'engineio/async_drivers/asgi.py' in pathname_str:
            if 'RuntimeError' in record.levelname or 'ERROR' in record.levelname:
                return False

        return True


# Filter out Starlette TemplateResponse deprecation warnings
class StarletteDeprecationFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # Suppress Starlette TemplateResponse deprecation warning
        # This is a known issue in Starlette/NiceGUI dependencies
        if 'TemplateResponse' in msg and 'is not the first parameter' in msg:
            return False
        if 'starlette/templating.py' in str(record.pathname) and 'DeprecationWarning' in record.levelname:
            return False
        return True

# Apply filters to relevant loggers
nicegui_logger = logging.getLogger('nicegui')
nicegui_logger.addFilter(DrawerTimeoutFilter())
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    nicegui_logger.addFilter(SocketIOErrorFilter())

# Also filter asyncio logger which reports Socket.IO task exceptions
asyncio_logger = logging.getLogger('asyncio')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    asyncio_logger.addFilter(SocketIOErrorFilter())

# Filter socketio logger directly if it exists
socketio_logger = logging.getLogger('socketio')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    socketio_logger.addFilter(SocketIOErrorFilter())
    socketio_logger.addFilter(WebSocketErrorFilter())
else:
    socketio_logger.setLevel(log_level)

# Filter engineio logger (used by socketio) - be very aggressive
engineio_logger = logging.getLogger('engineio')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    engineio_logger.addFilter(WebSocketErrorFilter())
    engineio_logger.setLevel(logging.CRITICAL)  # Only show critical errors
else:
    engineio_logger.setLevel(log_level)

# Filter websockets logger - be very aggressive
websockets_logger = logging.getLogger('websockets')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    websockets_logger.addFilter(WebSocketErrorFilter())
    websockets_logger.setLevel(logging.CRITICAL)  # Only show critical errors
else:
    websockets_logger.setLevel(log_level)

# Filter websockets.legacy specifically
websockets_legacy_logger = logging.getLogger('websockets.legacy')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    websockets_legacy_logger.addFilter(WebSocketErrorFilter())
    websockets_legacy_logger.setLevel(logging.CRITICAL)
else:
    websockets_legacy_logger.setLevel(log_level)

# Filter websockets.legacy.server specifically
websockets_legacy_server_logger = logging.getLogger('websockets.legacy.server')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    websockets_legacy_server_logger.addFilter(WebSocketErrorFilter())
    websockets_legacy_server_logger.setLevel(logging.CRITICAL)
else:
    websockets_legacy_server_logger.setLevel(log_level)

# Filter Starlette deprecation warnings
starlette_logger = logging.getLogger('starlette')
starlette_logger.addFilter(StarletteDeprecationFilter())

# Filter uvicorn websocket errors - be very aggressive
uvicorn_logger = logging.getLogger('uvicorn')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    uvicorn_logger.addFilter(WebSocketErrorFilter())

# Filter uvicorn.protocols.websockets specifically - suppress ALL messages
uvicorn_protocol_logger = logging.getLogger('uvicorn.protocols.websockets')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    uvicorn_protocol_logger.addFilter(WebSocketErrorFilter())
    uvicorn_protocol_logger.setLevel(logging.CRITICAL + 1)  # Disable all logging
else:
    uvicorn_protocol_logger.setLevel(log_level)

# Filter uvicorn.protocols.websockets.websockets_impl specifically
uvicorn_websockets_impl_logger = logging.getLogger('uvicorn.protocols.websockets.websockets_impl')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    uvicorn_websockets_impl_logger.addFilter(WebSocketErrorFilter())
    uvicorn_websockets_impl_logger.setLevel(logging.CRITICAL + 1)  # Disable all logging
else:
    uvicorn_websockets_impl_logger.setLevel(log_level)

# Filter uvicorn.error logger which catches exceptions - be very aggressive
uvicorn_error_logger = logging.getLogger('uvicorn.error')
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    uvicorn_error_logger.addFilter(WebSocketErrorFilter())

# Also add a more aggressive filter that checks the entire traceback
class AggressiveWebSocketFilter(logging.Filter):
    """Very aggressive filter for websocket errors that checks full message and traceback"""
    def filter(self, record):
        msg = str(record.getMessage()).lower()
        pathname = str(record.pathname or '').lower()
        funcname = str(record.funcName or '').lower()
        module = str(record.module or '').lower()

        # Build full message including exception traceback if available
        full_msg_parts = [msg, pathname, funcname, module]

        # Include exception info if present
        if record.exc_info and record.exc_info[2]:
            import traceback
            try:
                tb_text = ''.join(traceback.format_exception(*record.exc_info)).lower()
                full_msg_parts.append(tb_text)
            except:
                pass

        full_msg = ' '.join(full_msg_parts).lower()

        # Comprehensive list of websocket-related keywords
        websocket_keywords = [
            'websocket', 'ws_handler', 'engineio', 'socketio',
            'asgi_send', 'message_type', 'http.response.start',
            'uvicorn.protocols.websockets', 'websockets_impl',
            'websockets_impl.py', 'exception in asgi application',
            'run_asgi', 'asgi_receive', 'asgi_send',
            'raise runtimeerror', 'message_type'
        ]

        # Check pathname patterns that indicate websocket-related modules
        websocket_paths = [
            'uvicorn/protocols/websockets',
            'engineio/async_drivers/asgi',
            'websockets/legacy'
        ]

        # If it matches any websocket-related pattern, suppress warnings and above
        if record.levelno >= logging.WARNING:
            if any(keyword in full_msg for keyword in websocket_keywords):
                return False
            if any(path_pattern in pathname for path_pattern in websocket_paths):
                return False

        return True

# Apply aggressive filter to uvicorn.error which logs exceptions
if _SUPPRESS_WEBSOCKET_LOG_NOISE:
    uvicorn_error_logger.addFilter(AggressiveWebSocketFilter())

# Also filter warnings module to catch deprecation warnings
warnings_logger = logging.getLogger('py.warnings')
warnings_logger.addFilter(StarletteDeprecationFilter())

# Filter Python's warnings for Starlette TemplateResponse deprecation
# This suppresses the deprecation warning from Starlette's TemplateResponse
warnings.filterwarnings('ignore', message='.*TemplateResponse.*is not the first parameter.*', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*The `name` is not the first parameter anymore.*', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*The first parameter should be the `Request` instance.*', category=DeprecationWarning)

# Filter websocket deprecation warnings - be very aggressive
warnings.filterwarnings('ignore', message='.*remove second argument of ws_handler.*', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*websockets.*legacy.*', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*websocket.*', category=DeprecationWarning, module='websockets.*')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='websockets.*')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='websockets.legacy.*')

# Filter RuntimeWarnings from websockets
warnings.filterwarnings('ignore', category=RuntimeWarning, module='websockets.*')
