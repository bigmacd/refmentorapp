"""Profile photo processing and storage.

Photos are stored on the user row as JPEG bytes (users.avatar_jpeg). Uploads are
center-cropped to a square, resized, converted to JPEG, and saved without EXIF
(so GPS and other camera metadata are not kept).

Legacy files in DATA_CACHE_DIR/avatars or .data/avatars are imported once into
the database, then removed.
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
AVATAR_SIZE = 256
JPEG_QUALITY = 85
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


def get_avatar_dir() -> Path:
    configured = os.environ.get('AVATAR_DIR', '').strip()
    if configured:
        return Path(configured)
    cache_dir = os.environ.get('DATA_CACHE_DIR', '').strip()
    if cache_dir:
        return Path(cache_dir) / 'avatars'
    return Path(__file__).resolve().parent / '.data' / 'avatars'


def avatar_path(user_id: int) -> Path:
    return get_avatar_dir() / f'{int(user_id)}.jpg'


def _db(db=None):
    if db is not None:
        return db
    from database import get_db
    return get_db()


def _forget_legacy_file(user_id: int) -> None:
    avatar_path(user_id).unlink(missing_ok=True)


def has_avatar(user_id: Optional[int], db=None) -> bool:
    if user_id is None:
        return False
    return _db(db).userHasAvatar(user_id)


def avatar_data_url(user_id: Optional[int], db=None) -> Optional[str]:
    if user_id is None:
        return None
    data = _db(db).getUserAvatar(user_id)
    if not data:
        return None
    encoded = base64.b64encode(data).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


def process_avatar_image(data: bytes) -> bytes:
    if not data:
        raise ValueError('Please choose a photo to upload.')
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError('That photo is too large. Please use an image under 5 MB.')

    try:
        image = Image.open(BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise ValueError('That file is not a supported image. Use JPEG, PNG, or WebP.') from exc
    except Image.DecompressionBombError as exc:
        raise ValueError('That image is too large to process.') from exc
    except OSError as exc:
        raise ValueError('Could not read that image. Try a different JPEG or PNG.') from exc

    fmt = (image.format or '').upper()
    if fmt and fmt not in ALLOWED_FORMATS:
        raise ValueError('That file is not a supported image. Use JPEG, PNG, or WebP.')

    image = ImageOps.exif_transpose(image) or image
    if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
        rgba = image.convert('RGBA')
        background = Image.new('RGB', rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    else:
        image = image.convert('RGB')

    width, height = image.size
    side = min(width, height)
    if side < 32:
        raise ValueError('That image is too small. Please use a photo at least 32 pixels square.')
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)

    out = BytesIO()
    image.save(out, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def save_avatar(user_id: int, data: bytes, db=None) -> None:
    processed = process_avatar_image(data)
    _db(db).setUserAvatar(user_id, processed)
    _forget_legacy_file(user_id)


def delete_avatar(user_id: int, db=None) -> None:
    _db(db).deleteUserAvatar(user_id)
    _forget_legacy_file(user_id)


def import_legacy_file_avatars(db) -> None:
    """Copy leftover on-disk avatars into users.avatar_jpeg, then delete the files."""
    directory = get_avatar_dir()
    if not directory.is_dir():
        return
    for path in sorted(directory.glob('*.jpg')):
        if path.name.endswith('.tmp'):
            continue
        try:
            user_id = int(path.stem)
        except ValueError:
            continue
        if db.getUserById(user_id) is None:
            logging.warning('Skipping avatar file with no matching user: %s', path)
            continue
        try:
            if not db.userHasAvatar(user_id):
                data = path.read_bytes()
                if not data:
                    continue
                db.setUserAvatar(user_id, data)
                logging.info('Imported avatar for user_id=%s from %s', user_id, path)
            path.unlink(missing_ok=True)
        except Exception:
            logging.exception('Could not import avatar file %s', path)
