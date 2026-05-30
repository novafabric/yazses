import stat
import sys

import pytest

from yazses.learning.crypto import Cipher, load_or_create_key


def test_load_or_create_key_creates_file_with_0600(tmp_path):
    data_dir = tmp_path / "yazses"
    key = load_or_create_key(data_dir)
    key_file = data_dir / "corpus.key"

    assert key_file.exists()
    assert len(key) == 32
    if sys.platform != "win32":
        # Windows uses ACLs, not Unix mode bits — skip permission assertions.
        mode = stat.S_IMODE(key_file.stat().st_mode)
        assert mode == 0o600
        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700


def test_load_or_create_key_is_stable(tmp_path):
    data_dir = tmp_path / "yazses"
    first = load_or_create_key(data_dir)
    second = load_or_create_key(data_dir)
    assert first == second


def test_cipher_roundtrip_bytes(tmp_path):
    key = load_or_create_key(tmp_path)
    cipher = Cipher(key)
    plaintext = b"hello \x00 binary \xff world"
    blob = cipher.encrypt(plaintext)
    assert blob != plaintext
    assert cipher.decrypt(blob) == plaintext


def test_cipher_roundtrip_str(tmp_path):
    key = load_or_create_key(tmp_path)
    cipher = Cipher(key)
    text = "the quick brown fox — café"
    assert cipher.decrypt_str(cipher.encrypt_str(text)) == text


def test_cipher_nonce_is_random(tmp_path):
    key = load_or_create_key(tmp_path)
    cipher = Cipher(key)
    a = cipher.encrypt(b"same")
    b = cipher.encrypt(b"same")
    assert a != b  # distinct nonces


def test_cipher_rejects_tampered_blob(tmp_path):
    key = load_or_create_key(tmp_path)
    cipher = Cipher(key)
    blob = bytearray(cipher.encrypt(b"secret"))
    blob[-1] ^= 0x01  # flip a ciphertext bit
    with pytest.raises(Exception):
        cipher.decrypt(bytes(blob))
