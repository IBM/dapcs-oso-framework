import pytest

from collections import Counter

from oso.framework.plugin.addons.signing_server import SigningServerAddon
from oso.framework.plugin.addons.signing_server._key import KeyType


@pytest.fixture
def signing_server(_env, monkeypatch, grpc_stub_mock):  # noqa: F401
    monkeypatch.setattr(
        "oso.framework.plugin.addons.signing_server.generated.server_pb2_grpc.CryptoStub",
        grpc_stub_mock,
    )
    from oso.framework.plugin.extension import PluginConfig  # noqa: F401
    from oso.framework.plugin.extension import PluginExtension
    from oso.framework.config import ConfigManager

    config = ConfigManager.reload()
    ext = PluginExtension(config.plugin)
    assert ext.addons
    return ext.addons["SigningServer"]


def test_init(signing_server: SigningServerAddon):
    assert signing_server is not None

    # assert isinstance(signing_server, (SigningServerAddon))
    assert signing_server.__class__.__name__ == "SigningServerAddon"


def test_health_check(signing_server: SigningServerAddon):
    component_status = signing_server.health_check()
    assert component_status.status_code == 200
    assert component_status.status == "OK"
    assert component_status.errors == []


def test_gen_key_pair(signing_server: SigningServerAddon):
    # Generate first secp256k1 key pair
    assert signing_server.list_keys(KeyType.SECP256K1) == []

    secp256k1_list = []

    secp256k1_key_id_1, secp256k1_pub_key_pem_1 = signing_server.generate_key_pair(
        key_type=KeyType.SECP256K1
    )

    secp256k1_list.append(secp256k1_key_id_1)

    assert Counter(signing_server.list_keys(KeyType.SECP256K1)) == Counter(
        secp256k1_list
    )

    assert (
        signing_server.get_key_pem(key_id=secp256k1_key_id_1) == secp256k1_pub_key_pem_1
    )

    # Generate second secp256k1 key pair

    secp256k1_key_id_2, secp256k1_pub_key_pem_2 = signing_server.generate_key_pair(
        key_type=KeyType.SECP256K1
    )

    secp256k1_list.append(secp256k1_key_id_2)

    assert Counter(signing_server.list_keys(KeyType.SECP256K1)) == Counter(
        secp256k1_list
    )

    assert (
        signing_server.get_key_pem(key_id=secp256k1_key_id_2) == secp256k1_pub_key_pem_2
    )

    # Generate first ed25519 key pair

    ed25519_list = []

    ed25519_key_id_1, ed25519_pub_key_pem_1 = signing_server.generate_key_pair(
        key_type=KeyType.ED25519
    )

    ed25519_list.append(ed25519_key_id_1)

    assert Counter(signing_server.list_keys(KeyType.ED25519)) == Counter(ed25519_list)

    assert signing_server.get_key_pem(key_id=ed25519_key_id_1) == ed25519_pub_key_pem_1

    # Generate second ed25519 key pair

    ed25519_key_id_2, ed25519_pub_key_pem_2 = signing_server.generate_key_pair(
        key_type=KeyType.ED25519
    )

    ed25519_list.append(ed25519_key_id_2)

    assert Counter(signing_server.list_keys(KeyType.ED25519)) == Counter(ed25519_list)

    assert signing_server.get_key_pem(key_id=ed25519_key_id_2) == ed25519_pub_key_pem_2

    # Re-check secp256k1 keys

    assert (
        signing_server.get_key_pem(key_id=secp256k1_key_id_2) == secp256k1_pub_key_pem_2
    )

    assert (
        signing_server.get_key_pem(key_id=secp256k1_key_id_2) == secp256k1_pub_key_pem_2
    )

    assert Counter(signing_server.list_keys(KeyType.SECP256K1)) == Counter(
        secp256k1_list
    )


def test_rewrap_key(signing_server: SigningServerAddon):
    """rewrap_key() re-wraps a single blob via the HSM."""
    assert signing_server.rewrap_key(b"blob") == b"blob\xff"
