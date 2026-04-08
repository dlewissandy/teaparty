#!/usr/bin/env python3
"""Tests for file_lock.py — advisory file locking utility."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from teaparty.util.file_lock import (
    locked_open, locked_append, locked_read_json, locked_write_json,
    LOCK_SUFFIX,
)


class TestLockedOpen(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "test.txt")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_mode_shared_lock(self):
        """Reading a file acquires shared lock and returns content."""
        with open(self.test_file, 'w') as f:
            f.write("hello world")
        with locked_open(self.test_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, "hello world")

    def test_write_mode_truncates(self):
        """Writing with 'w' mode truncates and replaces content."""
        with open(self.test_file, 'w') as f:
            f.write("old content")
        with locked_open(self.test_file, 'w') as f:
            f.write("new content")
        with open(self.test_file) as f:
            self.assertEqual(f.read(), "new content")

    def test_append_mode(self):
        """Appending adds to existing content."""
        with open(self.test_file, 'w') as f:
            f.write("first")
        with locked_open(self.test_file, 'a') as f:
            f.write(" second")
        with open(self.test_file) as f:
            self.assertEqual(f.read(), "first second")

    def test_rw_mode_read_modify_write(self):
        """Read-write mode allows read, seek, truncate, rewrite."""
        with open(self.test_file, 'w') as f:
            f.write("original")
        with locked_open(self.test_file, 'rw') as f:
            content = f.read()
            self.assertEqual(content, "original")
            f.seek(0)
            f.truncate()
            f.write("modified")
        with open(self.test_file) as f:
            self.assertEqual(f.read(), "modified")

    def test_rw_creates_file_if_missing(self):
        """Read-write mode creates the file if it doesn't exist."""
        new_file = os.path.join(self.tmpdir, "new.txt")
        with locked_open(new_file, 'rw') as f:
            f.write("created")
        with open(new_file) as f:
            self.assertEqual(f.read(), "created")

    def test_lock_file_created(self):
        """A .lock file is created adjacent to the target file."""
        with open(self.test_file, 'w') as f:
            f.write("data")
        lock_path = self.test_file + LOCK_SUFFIX
        self.assertFalse(os.path.exists(lock_path))
        with locked_open(self.test_file, 'r') as f:
            self.assertTrue(os.path.exists(lock_path))

    def test_timeout_raises(self):
        """Lock acquisition times out if another lock is held."""
        import fcntl

        with open(self.test_file, 'w') as f:
            f.write("data")

        # Hold an exclusive lock on the lock file
        lock_path = self.test_file + LOCK_SUFFIX
        lock_fd = open(lock_path, 'w')
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

        try:
            with self.assertRaises(TimeoutError):
                with locked_open(self.test_file, 'w', timeout=0.2) as f:
                    f.write("should not reach here")
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()


class TestLockedAppend(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, "append.txt")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_append(self):
        """Append adds text to a file."""
        with open(self.test_file, 'w') as f:
            f.write("line1\n")
        locked_append(self.test_file, "line2\n")
        with open(self.test_file) as f:
            self.assertEqual(f.read(), "line1\nline2\n")

    def test_concurrent_appends_no_data_loss(self):
        """Multiple threads appending concurrently don't lose data."""
        with open(self.test_file, 'w') as f:
            pass  # empty file

        num_threads = 10
        lines_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def append_lines(thread_id):
            barrier.wait()  # synchronize start
            for i in range(lines_per_thread):
                locked_append(self.test_file, f"t{thread_id}-{i}\n")

        threads = [threading.Thread(target=append_lines, args=(t,))
                   for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with open(self.test_file) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

        expected_count = num_threads * lines_per_thread
        self.assertEqual(len(lines), expected_count,
                         f"Expected {expected_count} lines, got {len(lines)}")

        # Verify all expected lines are present
        expected = {f"t{t}-{i}" for t in range(num_threads)
                    for i in range(lines_per_thread)}
        self.assertEqual(set(lines), expected)


class TestLockedJson(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.json_file = os.path.join(self.tmpdir, "data.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read_json(self):
        """Write JSON then read it back."""
        data = {"key": "value", "count": 42}
        locked_write_json(self.json_file, data)
        result = locked_read_json(self.json_file)
        self.assertEqual(result, data)

    def test_read_missing_returns_default(self):
        """Reading a missing file returns the default."""
        result = locked_read_json(self.json_file, default={"empty": True})
        self.assertEqual(result, {"empty": True})

    def test_read_corrupt_returns_default(self):
        """Reading corrupt JSON returns the default."""
        with open(self.json_file, 'w') as f:
            f.write("not json {{{")
        result = locked_read_json(self.json_file, default=None)
        self.assertIsNone(result)

    def test_write_json_atomic(self):
        """Write uses atomic rename — file is never partially written."""
        locked_write_json(self.json_file, {"initial": True})

        # Write again — should atomically replace
        locked_write_json(self.json_file, {"replaced": True, "data": list(range(100))})

        with open(self.json_file) as f:
            data = json.load(f)
        self.assertTrue(data["replaced"])
        self.assertEqual(len(data["data"]), 100)

    def test_concurrent_write_json(self):
        """Multiple threads writing JSON concurrently don't corrupt the file."""
        num_threads = 10
        barrier = threading.Barrier(num_threads)

        def write_json(thread_id):
            barrier.wait()
            locked_write_json(self.json_file, {"thread": thread_id, "data": list(range(50))})

        threads = [threading.Thread(target=write_json, args=(t,))
                   for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # File should be valid JSON from one of the threads (last writer wins)
        with open(self.json_file) as f:
            data = json.load(f)
        self.assertIn("thread", data)
        self.assertEqual(len(data["data"]), 50)


if __name__ == '__main__':
    unittest.main()
