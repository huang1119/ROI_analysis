"""测试 src/accounts.py：账户管理。"""
import src.accounts as acc


def test_default_accounts():
    assert len(acc.DEFAULT_ACCOUNTS) == 2
    assert {a["advertiser_id"] for a in acc.DEFAULT_ACCOUNTS} == {"A001", "A002"}


def test_save_and_load_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(acc, "ACCOUNTS_PATH", tmp_path / "accounts.json")
    acc.save_accounts([{"advertiser_id": "X1", "advertiser_name": "测试店"}])
    assert acc.load_accounts() == [{"advertiser_id": "X1", "advertiser_name": "测试店"}]
