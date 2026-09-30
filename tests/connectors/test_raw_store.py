"""Raw payloads are content-addressed, write-once and verifiable."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from src.connectors.raw_store import (
    FetchRecord,
    RawStore,
    RawStoreError,
    sha256_bytes,
    sha256_file,
)


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path)


def test_a_payload_lands_at_its_content_hash(store: RawStore, tmp_path: Path) -> None:
    payload = store.save("census", b"hello", ".csv")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert payload.sha256 == expected and payload.size == 5
    assert payload.path == tmp_path / "census" / f"{expected}.csv"
    assert payload.path.read_bytes() == b"hello"


def test_a_stored_payload_is_read_only(store: RawStore) -> None:
    payload = store.save("census", b"hello", ".csv")
    assert stat.S_IMODE(payload.path.stat().st_mode) == 0o444


def test_saving_identical_bytes_again_is_a_noop(store: RawStore) -> None:
    first = store.save("census", b"hello", ".csv")
    before = first.path.stat().st_mtime_ns
    second = store.save("census", b"hello", ".csv")
    assert second == first and second.path.stat().st_mtime_ns == before


def test_new_content_never_replaces_old(store: RawStore) -> None:
    old = store.save("census", b"release one", ".csv")
    new = store.save("census", b"release two", ".csv")
    assert old.path != new.path
    assert old.path.read_bytes() == b"release one"  # the earlier release is intact


def test_a_tampered_file_is_detected_on_save_and_on_verify(store: RawStore) -> None:
    payload = store.save("census", b"hello", ".csv")
    os.chmod(payload.path, 0o644)
    payload.path.write_bytes(b"HELLO")  # someone edits the stored bytes
    with pytest.raises(RawStoreError, match="no longer matches"):
        store.save("census", b"hello", ".csv")
    with pytest.raises(RawStoreError, match="modified after it was stored"):
        store.verify(payload)


def test_no_partial_files_are_left_behind(store: RawStore, tmp_path: Path) -> None:
    store.save("census", b"hello", ".csv")
    leftovers = [p.name for p in (tmp_path / "census").iterdir() if p.name.startswith(".partial")]
    assert leftovers == []


@pytest.mark.parametrize("source", ["../evil", "Bad", "has space", "", "a/b", "1abc"])
def test_unsafe_source_names_are_refused(store: RawStore, source: str) -> None:
    with pytest.raises(RawStoreError, match="unsafe source name"):
        store.save(source, b"x", ".csv")


@pytest.mark.parametrize("suffix", ["csv", ".tar.gz", "../x", ".", ".CSV", ".toolongsuffix"])
def test_unsafe_suffixes_are_refused(store: RawStore, suffix: str) -> None:
    with pytest.raises(RawStoreError, match="unsafe file suffix"):
        store.save("census", b"x", suffix)


def test_a_malformed_hash_is_refused(store: RawStore) -> None:
    with pytest.raises(RawStoreError, match="64 lower-case hex"):
        store.path_for("census", "ABC", ".csv")


def test_chunked_file_hashing_matches_hashing_the_bytes(tmp_path: Path) -> None:
    content = os.urandom(2_500_000)  # more than two 1 MiB chunks
    path = tmp_path / "big.bin"
    path.write_bytes(content)
    assert sha256_file(path) == sha256_bytes(content)


def test_fetch_records_round_trip(store: RawStore) -> None:
    assert store.get_record("census", "req") is None
    record = FetchRecord(
        sha256="a" * 64, suffix=".csv", etag='"v1"', last_modified="Mon, 01 Jan 2024"
    )
    store.put_record("census", "req", record)
    store.put_record("census", "other", FetchRecord(sha256="b" * 64, suffix=".json"))
    assert store.get_record("census", "req") == record
    assert store.get_record("census", "other") == FetchRecord(sha256="b" * 64, suffix=".json")
