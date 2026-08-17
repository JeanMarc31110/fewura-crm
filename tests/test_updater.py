from fewura_crm import updater


def test_version_comparison_is_numeric():
    assert updater._version("v1.10.0") > updater._version("v1.9.9")
    assert updater._version("release-1.4.3") == (1, 4, 3)


def test_no_update_when_release_is_not_newer(monkeypatch):
    monkeypatch.setattr(
        updater,
        "_get_latest",
        lambda: {"tag_name": "v1.4.3", "assets": []},
    )
    assert updater.maybe_update("1.4.3") is False


def test_update_check_fails_open(monkeypatch):
    def fail():
        raise OSError("offline")
    monkeypatch.setattr(updater, "_get_latest", fail)
    assert updater.maybe_update("1.4.3") is False
