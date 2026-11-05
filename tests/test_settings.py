"""`Settings.from_env`: configuração por ambiente, sem segredo no código (chaves obviamente falsas)."""

import pytest
from app.sessions.credentials import hash_token
from app.settings import ConfigError, Settings

FAKE_SECRET = "fake-session-secret-for-tests-only-0123456789"
FAKE_TUTOR = "fake-tutor-service-token-for-tests-only-01"
FAKE_SYSTEM = "fake-system-service-token-for-tests-only-02"
FAKE_VISION = "fake-vision-service-token-for-tests-only-03"
BASE = {"DATABASE_URL": "sqlite:///fake.db", "SESSION_TOKEN_SECRET": FAKE_SECRET}


def test_from_env_reads_secret_and_hashes_service_tokens():
    env = {
        **BASE,
        "SERVICE_TOKEN_TUTOR": FAKE_TUTOR,
        "SERVICE_TOKEN_SYSTEM": FAKE_SYSTEM,
        "SERVICE_TOKEN_VISION_WORKER": FAKE_VISION,
    }
    settings = Settings.from_env(env)
    assert settings.database_url == "sqlite:///fake.db"
    assert settings.session_token_secret == FAKE_SECRET.encode()
    assert settings.service_token_hashes == {
        hash_token(FAKE_TUTOR): "tutor",
        hash_token(FAKE_SYSTEM): "system",
        hash_token(FAKE_VISION): "vision_worker",
    }
    # Só o hash fica na configuração; o token em claro não.
    assert FAKE_TUTOR not in repr(settings.service_token_hashes)


def test_missing_service_token_turns_that_actor_off():
    settings = Settings.from_env({**BASE, "SERVICE_TOKEN_TUTOR": FAKE_TUTOR})
    assert list(settings.service_token_hashes.values()) == ["tutor"]
    assert Settings.from_env({**BASE, "SERVICE_TOKEN_SYSTEM": ""}).service_token_hashes == {}


@pytest.mark.parametrize(
    "env",
    [
        {"SESSION_TOKEN_SECRET": FAKE_SECRET},
        {"DATABASE_URL": "sqlite:///fake.db"},
        {**BASE, "SESSION_TOKEN_SECRET": "tiny-value"},
        {**BASE, "SERVICE_TOKEN_TUTOR": "tiny-value"},
        {**BASE, "SERVICE_TOKEN_TUTOR": FAKE_TUTOR, "SERVICE_TOKEN_SYSTEM": FAKE_TUTOR},
    ],
)
def test_insecure_or_missing_configuration_fails(env):
    with pytest.raises(ConfigError) as e:
        Settings.from_env(env)
    assert "tiny-value" not in str(e.value) and FAKE_TUTOR not in str(e.value)
