"""Tests for koda2.modules.messaging.whatsapp_guard."""

import time
import pytest

from koda2.modules.messaging.whatsapp_guard import WhatsAppGuard


# ---------------------------------------------------------------------------
# Protection 1: extract_messages filters statuses-only payloads
# ---------------------------------------------------------------------------

def test_extract_messages_ignores_statuses_only():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{"id": "wamid.xxx", "status": "delivered"}]
                }
            }]
        }]
    }
    assert WhatsAppGuard.extract_messages(payload) == []


def test_extract_messages_returns_inbound():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [
                        {"id": "wamid.123", "from": "1234567890", "text": {"body": "hi"}}
                    ]
                }
            }]
        }]
    }
    msgs = WhatsAppGuard.extract_messages(payload)
    assert len(msgs) == 1
    assert msgs[0]["id"] == "wamid.123"


def test_extract_messages_with_both_statuses_and_messages():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{"id": "wamid.xxx", "status": "read"}],
                    "messages": [
                        {"id": "wamid.456", "from": "111", "text": {"body": "yo"}}
                    ]
                }
            }]
        }]
    }
    msgs = WhatsAppGuard.extract_messages(payload)
    assert len(msgs) == 1


# ---------------------------------------------------------------------------
# Protection 2: self-message detection
# ---------------------------------------------------------------------------

def test_drops_self_messages():
    guard = WhatsAppGuard(own_phone_number="+1 234 567 8900")
    assert guard.should_process("wamid.1", "12345678900", "12345678900") is False


def test_allows_other_sender():
    guard = WhatsAppGuard(own_phone_number="12345678900")
    assert guard.should_process("wamid.2", "9876543210", "9876543210") is True


# ---------------------------------------------------------------------------
# Protection 3: message ID deduplication
# ---------------------------------------------------------------------------

def test_dedup_blocks_duplicate():
    guard = WhatsAppGuard()
    assert guard.should_process("wamid.dup", "111", "111") is True
    assert guard.should_process("wamid.dup", "111", "111") is False


def test_dedup_allows_different_ids():
    guard = WhatsAppGuard()
    assert guard.should_process("wamid.a", "111", "111") is True
    assert guard.should_process("wamid.b", "111", "111") is True


# ---------------------------------------------------------------------------
# Protection 4: per-conversation cooldown
# ---------------------------------------------------------------------------

def test_cooldown_blocks_after_outgoing():
    guard = WhatsAppGuard(cooldown=2.0)
    guard.record_outgoing("conv1")
    # Immediately after sending, inbound should be blocked
    assert guard.should_process("wamid.c1", "222", "conv1") is False


def test_cooldown_allows_after_expiry():
    guard = WhatsAppGuard(cooldown=0.05)  # 50ms cooldown for fast test
    guard.record_outgoing("conv2")
    time.sleep(0.06)
    assert guard.should_process("wamid.c2", "333", "conv2") is True


def test_cooldown_does_not_affect_other_conversations():
    guard = WhatsAppGuard(cooldown=2.0)
    guard.record_outgoing("conv_a")
    assert guard.should_process("wamid.c3", "444", "conv_b") is True


# ---------------------------------------------------------------------------
# Protection 5: loop detection
# ---------------------------------------------------------------------------

def test_loop_detection_triggers():
    guard = WhatsAppGuard(loop_window=10.0, loop_max=5)
    conv = "loop_conv"
    for i in range(5):
        assert guard.should_process(f"wamid.loop{i}", "555", conv) is True
    # 6th message should be blocked
    assert guard.should_process("wamid.loop5", "555", conv) is False


def test_loop_detection_resets_after_window():
    guard = WhatsAppGuard(loop_window=0.05, loop_max=3)  # 50ms window
    conv = "loop_conv2"
    for i in range(3):
        guard.should_process(f"wamid.lr{i}", "666", conv)
    # Should be blocked now
    assert guard.should_process("wamid.lr3", "666", conv) is False
    # Wait for window to expire
    time.sleep(0.06)
    assert guard.should_process("wamid.lr4", "666", conv) is True


# ---------------------------------------------------------------------------
# Combined scenario
# ---------------------------------------------------------------------------

def test_combined_protections():
    guard = WhatsAppGuard(
        own_phone_number="100",
        cooldown=0.05,
        loop_window=10.0,
        loop_max=100,
    )
    # Self-message blocked
    assert guard.should_process("wamid.x1", "100", "100") is False
    # Normal message allowed
    assert guard.should_process("wamid.x2", "200", "200") is True
    # Duplicate blocked
    assert guard.should_process("wamid.x2", "200", "200") is False
    # Cooldown after outgoing
    guard.record_outgoing("300")
    assert guard.should_process("wamid.x3", "300", "300") is False
    time.sleep(0.06)
    assert guard.should_process("wamid.x4", "300", "300") is True
