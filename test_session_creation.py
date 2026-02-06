#!/usr/bin/env python3
"""Test script to verify Amplifier session creation works."""

import asyncio
import sys
from pathlib import Path

# Add the module to path
sys.path.insert(0, str(Path(__file__).parent))

from amplifier_chic.session_manager import SessionManager


async def test_session_creation():
    """Test creating a new Amplifier session."""
    print("Testing Amplifier session creation...")
    print()
    
    try:
        manager = SessionManager()
        print("✅ SessionManager initialized")
        
        print("📝 Starting new session (this may take a moment)...")
        await manager.start_new_session()
        
        print(f"✅ Session created successfully!")
        print(f"   Session ID: {manager.session_id}")
        print(f"   Session object: {type(manager.session).__name__}")
        print()
        
        # Try sending a simple message
        print("📤 Sending test message...")
        response = await manager.send_message("Say 'hello' in one word")
        print(f"✅ Got response: {response[:100]}...")
        print()
        print("🎉 ALL TESTS PASSED - Amplifier integration working!")
        
    except ImportError as e:
        print(f"❌ Import error (Amplifier not available): {e}")
        return False
    except AttributeError as e:
        print(f"❌ Attribute error (API mismatch): {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_session_creation())
    sys.exit(0 if success else 1)
