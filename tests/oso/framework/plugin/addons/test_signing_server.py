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


def test_rewrap_keys(signing_server: SigningServerAddon):
    """rewrap_keys() rewraps every stored private-key blob in place."""
    import pathlib

    secp_id, _ = signing_server.generate_key_pair(KeyType.SECP256K1)
    ed_id, _ = signing_server.generate_key_pair(KeyType.ED25519)

    keystore = pathlib.Path(signing_server._config.keystore_path)
    secp_file = keystore / "SECP256K1" / f"{secp_id}.key"
    ed_file = keystore / "ED25519" / f"{ed_id}.key"
    secp_before, ed_before = secp_file.read_bytes(), ed_file.read_bytes()
    (keystore / "ED25519" / "orphan.key").write_bytes(b"no pub")  # skipped

    assert Counter(signing_server.rewrap_keys("r1")) == Counter([secp_id, ed_id])
    assert secp_file.read_bytes() == secp_before + b"\xff"
    assert ed_file.read_bytes() == ed_before + b"\xff"
    assert (keystore / "ED25519" / "orphan.key").read_bytes() == b"no pub"
    assert signing_server.rewrap_key(b"blob") == b"blob\xff"

    # Done: a repeat returns the stored result without rewrapping again.
    assert Counter(signing_server.rewrap_keys("r1")) == Counter([secp_id, ed_id])
    assert secp_file.read_bytes() == secp_before + b"\xff"

    # A later rotation prunes the previous rotation's backups.
    signing_server.rewrap_keys("r2")
    assert sorted(p.name.split(".", 2)[2] for p in keystore.glob("*/*.orig")) == [
        "r2.orig",
        "r2.orig",
    ]

    with pytest.raises(ValueError, match="Invalid rotation_id"):
        signing_server.rewrap_keys("../escape")


def test_rewrap_keys_retry_after_partial_failure(signing_server: SigningServerAddon):
    """A retry rewraps each original blob once, even if some were already done."""
    import pathlib

    from unittest.mock import patch

    ids = [signing_server.generate_key_pair(KeyType.SECP256K1)[0] for _ in range(2)]
    keystore = pathlib.Path(signing_server._config.keystore_path)
    files = [keystore / "SECP256K1" / f"{i}.key" for i in ids]
    before = [f.read_bytes() for f in files]

    real = signing_server._grep11_client.rewrap_key
    calls = iter([real, RuntimeError("hsm down")])

    def flaky(blob: bytes) -> bytes:
        step = next(calls, real)
        if isinstance(step, Exception):
            raise step
        return step(blob)

    with patch.object(signing_server._grep11_client, "rewrap_key", flaky):
        with pytest.raises(RuntimeError):
            signing_server.rewrap_keys("r")
    changed = [f.read_bytes() != b for f, b in zip(files, before)]
    assert sorted(changed) == [False, True]  # first key done, second failed
    assert not (keystore / ".mk_rotation" / "r.json").exists()

    signing_server.rewrap_keys("r")
    assert [f.read_bytes() for f in files] == [b + b"\xff" for b in before]
    assert not list(keystore.glob("*/*.tmp"))
