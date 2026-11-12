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


def _all_key_files(ss: SigningServerAddon):
    ids = ss.list_keys(KeyType.SECP256K1) + ss.list_keys(KeyType.ED25519)
    return ids, [next(ss._keystore.glob(f"*/{i}.key")) for i in ids]


def test_rewrap_keystore(signing_server: SigningServerAddon):
    """Every key is rewrapped and the rotation backups are removed."""
    assert signing_server.rewrap_keystore("r0") == []  # empty keystore

    signing_server.generate_key_pair(KeyType.SECP256K1)
    signing_server.generate_key_pair(KeyType.ED25519)
    ids, files = _all_key_files(signing_server)
    before = [f.read_bytes() for f in files]

    assert sorted(signing_server.rewrap_keystore("r1")) == sorted(ids)
    assert [f.read_bytes() for f in files] == [b + b"\xff" for b in before]
    assert not (signing_server._keystore / ".mk_rotation").exists()
    assert not list(signing_server._keystore.rglob("*.tmp"))


def test_rewrap_keystore_rejects_unsafe_id(signing_server: SigningServerAddon):
    with pytest.raises(ValueError, match="Invalid mk_rotation_request_id"):
        signing_server.rewrap_keystore("../escape")


def test_rewrap_keystore_retry_after_partial_failure(
    signing_server: SigningServerAddon, monkeypatch
):
    """A retry rewraps the original blobs, never an already-rewrapped one."""
    signing_server.generate_key_pair(KeyType.SECP256K1)
    signing_server.generate_key_pair(KeyType.ED25519)
    _, files = _all_key_files(signing_server)
    before = [f.read_bytes() for f in files]

    real = signing_server.rewrap_key
    calls = iter([real, RuntimeError("hsm down")])

    def flaky(blob: bytes) -> bytes:
        step = next(calls, real)
        if isinstance(step, Exception):
            raise step
        return step(blob)

    monkeypatch.setattr(signing_server, "rewrap_key", flaky)
    with pytest.raises(RuntimeError):
        signing_server.rewrap_keystore("r")
    assert (signing_server._keystore / ".mk_rotation" / "r").exists()

    signing_server.rewrap_keystore("r")
    assert [f.read_bytes() for f in files] == [b + b"\xff" for b in before]
    assert not list(signing_server._keystore.rglob("*.tmp"))
    assert not (signing_server._keystore / ".mk_rotation").exists()
