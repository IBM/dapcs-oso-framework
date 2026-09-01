import pkcs11
import pytest
import datetime
import base64

from asn1crypto import core as asn1_core

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.hazmat.primitives.asymmetric import ed25519

from oso.framework.plugin.addons.signing_server.generated import server_pb2
from oso.framework.plugin.addons.signing_server._key import SECP256K1_Key, ED25519_Key


@pytest.fixture
def set_grep11_certs(monkeypatch):
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now())
        .not_valid_after(datetime.datetime.now() + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(encoding=serialization.Encoding.PEM)

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__CA_CERT",
        base64.b64encode(cert_pem).decode(),
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__CLIENT_KEY",
        base64.b64encode(key_pem).decode(),
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__CLIENT_CERT",
        base64.b64encode(cert_pem).decode(),
    )


@pytest.fixture
def secp256k1_key_pair():
    private_key = ec.generate_private_key(ec.SECP256K1())
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    ec_point_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return {
        "private_key": private_key,
        "public_key": public_key,
        "private_bytes": private_bytes,
        "ec_point_bytes": ec_point_bytes,
        "public_bytes": public_pem,
    }


@pytest.fixture
def ed25519_key_pair():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    ec_point_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return {
        "private_key": private_key,
        "public_key": public_key,
        "private_bytes": private_bytes,
        "ec_point_bytes": ec_point_bytes,  # actually just raw Ed25519 key bytes
        "public_bytes": public_pem,
    }


@pytest.fixture
def grpc_stub_mock(secp256k1_key_pair, ed25519_key_pair):
    # Create a class to mock the stub
    class MockCryptoStub:
        def __init__(self, _=None):
            pass

        def GenerateKeyPair(self, request: server_pb2.GenerateKeyPairRequest):
            priv_key = server_pb2.KeyBlob()

            ec_point_bytes = None

            match request.PubKeyTemplate[pkcs11.Attribute.EC_PARAMS].AttributeB.hex():
                case SECP256K1_Key.Oid:
                    ec_point_bytes = secp256k1_key_pair["ec_point_bytes"]
                case ED25519_Key.Oid:
                    ec_point_bytes = ed25519_key_pair["ec_point_bytes"]
                case _:
                    raise Exception("Unsupported Key OID")

            octet_string = asn1_core.OctetString(ec_point_bytes)

            der_encoded_ec_point = octet_string.dump()

            ec_point_attribute_value = server_pb2.AttributeValue(
                AttributeB=der_encoded_ec_point
            )

            pub_key = server_pb2.KeyBlob(
                Attributes={pkcs11.Attribute.EC_POINT: ec_point_attribute_value}
            )

            response = server_pb2.GenerateKeyPairResponse(
                PrivKey=priv_key, PubKey=pub_key
            )

            return response

        def GetMechanismList(self, _):
            return server_pb2.GetMechanismListResponse(
                Mechs=[
                    pkcs11.Mechanism.ECDSA,
                    pkcs11.Mechanism._VENDOR_DEFINED + 0x1001C,
                ]
            )

        def RewrapKeyBlob(self, request: server_pb2.RewrapKeyBlobRequest):
            # Echo back the same blob with a sentinel byte appended so tests
            # can verify the new blob differs from the original.
            rewrapped = request.WrappedKeyBytes + b"\xff"
            return server_pb2.RewrapKeyBlobResponse(RewrappedKeyBytes=rewrapped)

    return MockCryptoStub


@pytest.fixture(autouse=True)
def _env(set_grep11_certs, monkeypatch, tmp_path):
    monkeypatch.setenv("APP__NAME", "test-app")
    monkeypatch.setenv("CERTS__CA", "test-ca")
    monkeypatch.setenv("CERTS__APP_CRT", "test-crt")
    monkeypatch.setenv("CERTS__APP_KEY", "test-key")
    monkeypatch.setenv(
        "PLUGIN__MODE",
        "frontend",
    )
    monkeypatch.setenv(
        "PLUGIN__APPLICATION",
        "oso.framework.plugin.test.isv_mod",
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__TYPE",
        "oso.framework.plugin.addons.signing_server",
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__GREP11_ENDPOINT",
        "localhost",
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__GREP11_PORT",
        "9876",
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__KEYSTORE_PATH",
        str(tmp_path),
    )
    monkeypatch.setenv(
        "PLUGIN__ADDONS__0__EXTRA",
        "test",
    )
