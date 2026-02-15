"""Tests for system prompt configuration."""

from koda2.config import get_system_prompt, ASSISTANT_NAME, USER_NAME


def test_default_system_prompt_contains_joyce():
    prompt = get_system_prompt()
    assert 'Joyce' in prompt
    assert 'Ronald' in prompt


def test_system_prompt_custom_names():
    prompt = get_system_prompt(assistant_name='TestBot', user_name='Alice')
    assert 'TestBot' in prompt
    assert 'Alice' in prompt
    assert 'Joyce' not in prompt


def test_system_prompt_never_mention_koda2():
    prompt = get_system_prompt()
    assert 'Koda2' not in prompt.replace('Noem jezelf NOOIT Koda2', '')
    # The instruction itself mentions Koda2 to forbid it, that's fine
    assert 'Noem jezelf NOOIT Koda2' in prompt


def test_system_prompt_forbids_json():
    prompt = get_system_prompt()
    assert 'JSON' in prompt
    assert 'technische data' in prompt


def test_default_names():
    assert ASSISTANT_NAME == 'Joyce'
    assert USER_NAME == 'Ronald'
