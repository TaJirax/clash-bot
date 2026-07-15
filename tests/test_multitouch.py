from clashbot.multitouch import find_multitouch_device


def test_find_multitouch_device_uses_capability_block():
    output = """add device 1: /dev/input/event6
  name: \"User Input\"
    ABS (0003): ABS_MT_SLOT ABS_MT_POSITION_X ABS_MT_POSITION_Y
add device 2: /dev/input/event5
  name: \"Mouse\"
"""
    assert find_multitouch_device(output) == "/dev/input/event6"


def test_find_multitouch_device_returns_none_without_mt_slots():
    assert find_multitouch_device("add device 1: /dev/input/event2\n KEY (1): KEY_A") is None
