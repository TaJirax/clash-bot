from clashbot.memu_input import infer_instance


def test_infer_instance_from_standard_memu_adb_port():
    assert infer_instance("127.0.0.1:21503") == 0
    assert infer_instance("127.0.0.1:21513") == 1
    assert infer_instance("127.0.0.1:21523") == 2


def test_infer_instance_rejects_non_memu_serial():
    assert infer_instance("emulator-5554") is None
    assert infer_instance("127.0.0.1:5555") is None
