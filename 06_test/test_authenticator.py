import pytest
from authenticator import Authenticator


@pytest.fixture
def authenticator():
    """
    各テストで使用するAuthenticatorインスタンスを生成する
    """
    return Authenticator()


def test_register_success(authenticator):
    """
    正常系：
    register()でユーザーが正しく登録され、
    users辞書に保存されることを確認する
    """
    authenticator.register("user1", "password123")
    assert authenticator.users["user1"] == "password123"


def test_register_duplicate_user(authenticator):
    """
    異常系：
    既に登録されているユーザー名でregister()を実行すると
    ValueErrorが発生することを確認する
    """
    authenticator.register("user1", "password123")
    with pytest.raises(ValueError, match="エラー: ユーザーは既に存在します。"):
        authenticator.register("user1", "newpassword")


@pytest.mark.parametrize("username, password", [
    ("user1", "password123"),
    ("JohnDoe123", "abc123"),
    ("testuser", "pass"),
])
def test_login_success(authenticator, username, password):
    """
    正常系：
    正しいユーザー名とパスワードでlogin()を実行すると
    「ログイン成功」が返ることを確認する
    """
    authenticator.register(username, password)
    result = authenticator.login(username, password)
    assert result == "ログイン成功"


@pytest.mark.parametrize("correct_password, wrong_password", [
    ("password123", "wrongpassword"),
    ("abc123", "ABC123"),
    ("pass", "pass123"),
])
def test_login_wrong_password(authenticator, correct_password, wrong_password):
    """
    異常系：
    正しいユーザー名だが誤ったパスワードでlogin()を実行すると
    ValueErrorが発生することを確認する
    """
    authenticator.register("user1", correct_password)
    with pytest.raises(ValueError, match="エラー: ユーザー名またはパスワードが正しくありません。"):
        authenticator.login("user1", wrong_password)
