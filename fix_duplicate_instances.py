"""
Fix for duplicate instance problem

The issue is a race condition in acquire_lock():
1. Process A checks PID file - doesn't exist
2. Process B checks PID file - doesn't exist  
3. Process A writes its PID
4. Process B writes its PID (overwrites A)
5. Both processes think they have the lock

Solution: Use file locking (fcntl) to make PID file operations atomic
"""

import os
import sys
from pathlib import Path

# Read the current start.py
with open('start.py', 'r') as f:
    content = f.read()

# Find the acquire_lock function and replace it
old_acquire = '''def acquire_lock() -> bool:
    """
    Acquire a single-instance lock.

    Returns:
        True if lock acquired successfully, False if another instance is running
    """
    global LOCK_ACQUIRED

    # Clean up old cleanup files (more than 1 minute old)
    # These are created during graceful shutdown and should be cleaned up
    for cleanup_file in Path.cwd().glob("*.pid.cleaning"):
        try:
            mtime = datetime.fromtimestamp(cleanup_file.stat().st_mtime)
            age = datetime.now() - mtime
            if age > timedelta(minutes=1):
                logger.info(f"Removing old cleanup file: {cleanup_file}")
                cleanup_file.unlink()
        except:
            pass

    # Check for existing PID file
    if PID_FILE.exists():'''

new_acquire = '''def acquire_lock() -> bool:
    """
    Acquire a single-instance lock using atomic file operations.
    
    Uses fcntl to prevent race conditions when multiple processes start simultaneously.

    Returns:
        True if lock acquired successfully, False if another instance is running
    """
    global LOCK_ACQUIRED
    import fcntl

    # Clean up old cleanup files (more than 1 minute old)
    # These are created during graceful shutdown and should be cleaned up
    for cleanup_file in Path.cwd().glob("*.pid.cleaning"):
        try:
            mtime = datetime.fromtimestamp(cleanup_file.stat().st_mtime)
            age = datetime.now() - mtime
            if age > timedelta(minutes=1):
                logger.info(f"Removing old cleanup file: {cleanup_file}")
                cleanup_file.unlink()
        except:
            pass

    # Use file locking to prevent race condition
    try:
        # Open (or create) PID file in exclusive mode
        lock_fd = os.open(str(PID_FILE), os.O_RDWR | os.O_CREAT, 0o644)
        
        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            # Another process has the lock
            os.close(lock_fd)
            logger.error("Another PerryPicks instance is already running (lock held)")
            logger.error(f"If this is incorrect, delete {PID_FILE} and try again")
            return False
        
        # Check for existing PID file
        if PID_FILE.exists():'''

if old_acquire in content:
    content = content.replace(old_acquire, new_acquire)
    
    # Write back
    with open('start.py', 'w') as f:
        f.write(content)
    
    print("✅ Fixed acquire_lock() to use file locking")
    print("✅ This prevents race conditions when multiple instances start simultaneously")
else:
    print("❌ Could not find the acquire_lock function to patch")
    sys.exit(1)
