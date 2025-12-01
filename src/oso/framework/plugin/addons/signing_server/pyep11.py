import ctypes
import os
import sys
from ctypes import byref, c_uint, c_ubyte, c_char_p,c_uint32, c_uint64, c_char, c_void_p, POINTER, c_ulong, cast, create_string_buffer, Structure
import binascii
from .ep11mechs import *

from pyasn1.type.univ import ObjectIdentifier

# Load the EP11 shared library
ep11 = ctypes.CDLL("libep11.so")

############################################################################################
############################################################################################
############################################################################################
############################################################################################
##########
##########             C TO PYTHON
##########
##########
############################################################################################
############################################################################################
############################################################################################
############################################################################################

# Constants  as defined in ep11.h and ep11adm.h
XCP_OK = 0
CKR_OK = 0
XCP_MOD_VERSION = 2
XCP_MFL_VIRTUAL = 0x10
XCP_MFL_PROBE = 0x40
XCP_MFL_MODULE = 0x02
XCP_TGT_INIT = c_uint64(0xFFFFFFFFFFFFFFFF)
XCP_ADM_REENCRYPT          = 25
CK_IBM_XCPQ_DOMAIN      =  3
CKR_FUNCTION_FAILED     =   0x00000006
XCP_SERIALNR_CHARS     =   8
XCP_ADMCTR_BYTES = 16
XCP_KEYCSUM_BYTES = 32  # ep11.h

# types as defined in ep11.h and ep11adm.h
# Define domain mask setter function
def XCPTGTMASK_SET_DOM(mask, domain):
    byte_index = domain // 8
    bit = 1 << (7 - (domain % 8))
    mask[byte_index] |= bit

MAX_FNAME_CHARS = 256
MAX_BLOB_SIZE = 9126  # adjust if needed
MAX_CSUMSIZE = 64     # adjust if needed

class XCP_ModuleSocket(ctypes.Structure):
    _fields_ = [
        ("host", c_char * (MAX_FNAME_CHARS + 1)),
        ("port", c_uint32),
    ]

class XCP_DomainPerf(ctypes.Structure):
    _fields_ = [
        ("lastperf", c_uint32 * 256),
    ]

class XCP_Module(ctypes.Structure):
    _fields_ = [
        ("version", c_uint32),
        ("flags", c_uint64),
        ("domains", c_uint32),
        ("domainmask", c_ubyte * 32),
        ("socket", XCP_ModuleSocket),
        ("module_nr", c_uint32),
        ("mhandle", c_void_p),
        ("perf", XCP_DomainPerf),
        ("api", c_uint32),
    ]

class CK_MECHANISM(Structure):
    _fields_ = [
        ("mechanism", c_ulong),       # CK_MECHANISM_TYPE
        ("pParameter", c_void_p),
        ("ulParameterLen", c_ulong),
    ]

class CK_ATTRIBUTE(Structure):
    _fields_ = [
        ("type", c_ulong),     # CK_ATTRIBUTE_TYPE is usually an unsigned integer (e.g., uint)
        ("pValue", c_void_p), # CK_VOID_PTR is usually a pointer to some data
        ("ulValueLen", c_ulong) # CK_ULONG is typically an unsigned long integer
    ]

# CK_IBM_DOMAIN_INFO struct
class CK_IBM_DOMAIN_INFO(Structure):
    _fields_ = [
        ("domain", c_ulong),
        ("wk", c_ubyte * XCP_KEYCSUM_BYTES),
        ("nextwk", c_ubyte * XCP_KEYCSUM_BYTES),
        ("flags", c_ulong),
        ("mode", c_ubyte * 8),
    ]

class XCPadmresp(ctypes.Structure):
    _fields_ = [
        ("fn", ctypes.c_uint32),
        ("domain", ctypes.c_uint32),
        ("domainInst", ctypes.c_uint32),
        ("module", ctypes.c_ubyte * (XCP_SERIALNR_CHARS + XCP_SERIALNR_CHARS)),  # Array of bytes
        ("modNr", ctypes.c_ubyte * XCP_SERIALNR_CHARS),  # Array of bytes
        ("modInst", ctypes.c_ubyte * XCP_SERIALNR_CHARS),  # Array of bytes
        ("tctr", ctypes.c_ubyte * XCP_ADMCTR_BYTES),  # Array of bytes
        ("rv", ctypes.c_ulong),
        ("reason", ctypes.c_uint32),
        ("payload", ctypes.POINTER(ctypes.c_ubyte)),  # Pointer to a byte array
        ("pllen", ctypes.c_size_t),  # Size of the payload
    ]

CK_MECHANISM_TYPE = ctypes.c_ulong  

# Define CK_MECHANISM structure
class CK_MECHANISM(ctypes.Structure):
    _fields_ = [
        ("mechanism", CK_MECHANISM_TYPE),   # CK_MECHANISM_TYPE can be adjusted as per the actual type
        ("pParameter", ctypes.c_void_p),    # CK_VOID_PTR equivalent to void pointer
        ("ulParameterLen", ctypes.c_ulong)  # CK_ULONG equivalent to unsigned long
    ]

# Declare function signatures
ep11.m_init.restype = ctypes.c_int
ep11.m_add_module.argtypes = [ctypes.POINTER(XCP_Module), ctypes.POINTER(ctypes.c_uint64)]
ep11.m_add_module.restype = ctypes.c_uint

############################################################################################
############################################################################################
############################################################################################
############################################################################################
##########
##########              Specific fonctions
##########
##########
############################################################################################
############################################################################################
############################################################################################
############################################################################################

OIDNamedCurveSecp256k1 = ObjectIdentifier('1.3.132.0.10')
OIDNamedCurveED25519= ObjectIdentifier('1.3.101.112')

# Initialize LoginBlob and LoginBlobLen to None and 0, respectively
LoginBlob = None
LoginBlobLen = 0

def SetLoginBlob(id_bytes):
    global LoginBlob, LoginBlobLen

    # Convert the Python byte array to a ctypes array of bytes
    LoginBlob = (ctypes.c_byte * len(id_bytes))(*id_bytes)

    # Set the length of the blob
    LoginBlobLen = len(id_bytes)

def toError(code):
    return f"Error code: {code}"

class Attribute:
    def __init__(self, attr_type, value):
        self.Type = c_ulong(attr_type)  # Equivalent to uint in Go
        if isinstance(value, bool):
            self.Value = bytes([1 if value else 0])
        elif isinstance(value, (int, ctypes.c_uint, ctypes.c_ulong)):
            self.Value = uint_to_bytes(value)
        elif isinstance(value, str):
            self.Value = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray)):
            self.Value = bytes(value)
        elif isinstance(value, datetime):  # CKA_DATE
            self.Value = value.strftime("%Y%m%d").encode("ascii")
        else:
            raise TypeError("Unhandled attribute value type")

        self.Length = c_ulong(len(self.Value))
       # self.Value = value  # This will be a byte string or byte array

    def get_value_as_buffer(self):
        """Convert the value into a ctypes buffer."""
        return create_string_buffer(self.Value)

    def __repr__(self):
        return f"Attribute(Type={self.Type}, Value={self.Value})"

class Arena:
    def __init__(self):
        self.allocations = []

    def allocate(self, buf):
        from ctypes import create_string_buffer
        b = create_string_buffer(bytes(buf))
        self.allocations.append(b)
        return cast(b, c_void_p), len(buf)

class Mechanism:
    def __init__(self, mechanism, parameter=None, generator=None):
        self.Mechanism = mechanism
        self.Parameter = parameter if parameter else []

def uint_to_bytes(val, length=8):
    return val.to_bytes(length, byteorder="big")

def convert_attributes_to_ck(attributes):
    arena = []  # to track allocated buffers
    ck_attrs = []

    for attr in attributes:
        val = attr.Value
        val_buf = (c_ubyte * len(attr.Value))(*attr.Value)
        arena.append(val_buf)
        val_len = len(val)
        #print(val)
        ck_attr = CK_ATTRIBUTE()
        ck_attr.type = attr.Type
        ck_attr.pValue = cast(val_buf, c_void_p) if val_buf else None

        ck_attr.ulValueLen = val_len
        ck_attrs.append(ck_attr)

    # Allocate final array
    #print(*ck_attrs)
    ck_array = (CK_ATTRIBUTE * len(ck_attrs))(*ck_attrs)
    return arena, ck_array, c_ulong(len(ck_attrs))

############################################################################################
############################################################################################
############################################################################################
############################################################################################
##########
##########              EP11 FONCTIONS
##########
##########
############################################################################################
############################################################################################
############################################################################################
############################################################################################

def GenerateKey(target, mechanism, temp_attributes):

    # Convert attributes and mechanisms to C types
    attrarena, t, tcount = convert_attributes_to_ck(temp_attributes)

    # Create mechanism directly
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0

    #   try:
    Key = create_string_buffer(MAX_BLOB_SIZE)
    CheckSum = create_string_buffer(MAX_CSUMSIZE)

    keyLenC = c_ulong(len(Key))
    checkSumLenC = c_ulong(len(Key))

    rc = ep11.m_GenerateKey(
        byref(mech_struct), t, tcount,
        LoginBlob, LoginBlobLen,
        cast(Key, POINTER(c_ubyte)), byref(keyLenC),
        cast(CheckSum, POINTER(c_ubyte)), byref(checkSumLenC),
        target
    )

    if rc != CKR_OK:
        return None, toError(rc)

    key_bytes = Key.raw[:keyLenC.value]
    checksum_bytes = CheckSum.raw[:checkSumLenC.value]

    return key_bytes, checksum_bytes , None

############################################################################################
############################################################################################

def EncryptSingle(target, mechanism, key, data):
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0   

    key_buf = (c_ubyte * len(key))(*key)
    keyC = cast(key_buf, POINTER(c_ubyte))
    keyLenC = c_ulong(len(key))

    # Prepare data
    data_buf = (c_ubyte * len(data))(*data)
    dataC = cast(data_buf, POINTER(c_ubyte))
    dataLenC = c_ulong(len(data))

    # Prepare signature buffer
    cipher = create_string_buffer(MAX_BLOB_SIZE)
    cipherC = cast(cipher, POINTER(c_ubyte))
    cipherLenC = c_ulong(MAX_BLOB_SIZE)

    # Call m_EncryptSingle
    rv = ep11.m_EncryptSingle(keyC, keyLenC, byref(mech_struct), dataC, dataLenC, cipherC, byref(cipherLenC), target)

    if rv != CKR_OK:
        e1 = toError(rv)
        return None, e1

    # Resize the cipher array based on the returned cipher length
    cipher = cipher[:cipherLenC.value]
    return cipher, None

############################################################################################
############################################################################################

def DecryptSingle(target, mechanism, key, cipher):
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0   

    key_buf = (c_ubyte * len(key))(*key)
    keyC = cast(key_buf, POINTER(c_ubyte))
    keyLenC = c_ulong(len(key))

    # Prepare data
    cipher_buf = (c_ubyte * len(cipher))(*cipher)
    cipherC = cast(cipher_buf, POINTER(c_ubyte))
    cipherLenC = c_ulong(len(cipher))

    # Prepare signature buffer
    plain = create_string_buffer(MAX_BLOB_SIZE)
    plainC = cast(plain, POINTER(c_ubyte))
    plainLenC = c_ulong(MAX_BLOB_SIZE)

    # Call m_EncryptSingle
    rv = ep11.m_DecryptSingle(keyC, keyLenC, byref(mech_struct), cipherC, cipherLenC, plainC, byref(plainLenC), target)

    if rv != CKR_OK:
        e1 = toError(rv)
        return None, e1

    # Resize the cipher array based on the returned cipher length
    plain = plain[:plainLenC.value]
    return plain, None

############################################################################################
############################################################################################

def ReencryptSingle(target, mechanism1, mechanism2, key1, key2, data):
    mech1arena = Arena()
    mech1_struct = CK_MECHANISM()
    mech1_struct.mechanism = c_ulong(mechanism1.Mechanism)

    if mechanism1.Parameter:
        buf_ptr, buf_len = mech1arena.allocate(mechanism1.Parameter)
        mech1_struct.pParameter = buf_ptr
        mech1_struct.ulParameterLen = buf_len
    else:
        mech1_struct.pParameter = None
        mech1_struct.ulParameterLen = 0  

    mech2arena = Arena()
    mech2_struct = CK_MECHANISM()
    mech2_struct.mechanism = c_ulong(mechanism2.Mechanism)

    if mechanism2.Parameter:
        buf_ptr, buf_len = mech2arena.allocate(mechanism2.Parameter)
        mech2_struct.pParameter = buf_ptr
        mech2_struct.ulParameterLen = buf_len
    else:
        mech2_struct.pParameter = None
        mech2_struct.ulParameterLen = 0       

    key1_buf = (c_ubyte * len(key1))(*key1)
    key1C = cast(key1_buf, POINTER(c_ubyte))
    key1LenC = c_ulong(len(key1))

    key2_buf = (c_ubyte * len(key2))(*key2)
    key2C = cast(key2_buf, POINTER(c_ubyte))
    key2LenC = c_ulong(len(key2))

    # Prepare data
    data_buf = (c_ubyte * len(data))(*data)
    dataC = cast(data_buf, POINTER(c_ubyte))
    dataLenC = c_ulong(len(data))

    # Prepare signature buffer
    cipher = create_string_buffer(MAX_BLOB_SIZE)
    cipherC = cast(cipher, POINTER(c_ubyte))
    cipherLenC = c_ulong(MAX_BLOB_SIZE)

    # Call m_EncryptSingle
    rv = ep11.m_ReencryptSingle(key1C, key1LenC, key2C, key2LenC, byref(mech1_struct), byref(mech2_struct), dataC, dataLenC, cipherC, byref(cipherLenC), target)

    if rv != CKR_OK:
        e1 = toError(rv)
        return None, e1

    # Resize the cipher array based on the returned cipher length
    cipher = cipher[:cipherLenC.value]
    return cipher, None

############################################################################################
############################################################################################

def GenerateKeyPair(target, mechanism, pk_attributes, sk_attributes):

    # Convert attributes and mechanisms to C types
    attrarena1, t1, tcount1 = convert_attributes_to_ck(pk_attributes)
    attrarena2, t2, tcount2 = convert_attributes_to_ck(sk_attributes)

    # Create mechanism directly
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0

    skKey = create_string_buffer(MAX_BLOB_SIZE)
    pkKey = create_string_buffer(MAX_BLOB_SIZE)

    skkeyLenC = c_ulong(len(skKey))
    pkkeyLenC = c_ulong(len(pkKey))

    rc = ep11.m_GenerateKeyPair(
        byref(mech_struct), t1, tcount1, t2, tcount2,
        LoginBlob, LoginBlobLen,
        cast(skKey, POINTER(c_ubyte)), byref(skkeyLenC),
        cast(pkKey, POINTER(c_ubyte)), byref(pkkeyLenC),
        target
    )

    if rc != CKR_OK:
        return None, toError(rc)

    sk_bytes = skKey.raw[:skkeyLenC.value]
    pk_bytes = pkKey.raw[:pkkeyLenC.value]
 
    return pk_bytes,sk_bytes, None

############################################################################################
############################################################################################

def SignSingle(target , mechanism, sk , data  ):
    # Create mechanism directly
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0
    
    if sk:
        sk_buf = (c_ubyte * len(sk))(*sk)
        privatekeyC = cast(sk_buf, POINTER(c_ubyte))
        privatekeyLenC = c_ulong(len(sk))
    else:
        privatekeyC = None
        privatekeyLenC = c_ulong(0)

    # Prepare data
    data_buf = (c_ubyte * len(data))(*data)
    dataC = cast(data_buf, POINTER(c_ubyte))
    datalenC = c_ulong(len(data))

    # Prepare signature buffer
    sig = create_string_buffer(MAX_BLOB_SIZE)
    sigC = cast(sig, POINTER(c_ubyte))
    siglenC = c_ulong(MAX_BLOB_SIZE)

    # Call C function
    rv = ep11.m_SignSingle(
        privatekeyC, privatekeyLenC,
        byref(mech_struct),
        dataC, datalenC,
        sigC, byref(siglenC),
        target
    )

    if rv != CKR_OK:
        return None, f"Sign error: {hex(rv)}"

    return sig.raw[:siglenC.value], None

############################################################################################
############################################################################################

def VerifySingle(target, mechanism, pk, data, sig):
    # Create mechanism directly
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0

    # Ensure inputs are bytes
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(sig, str):
        sig = sig.encode("utf-8")

    # Convert public key, data, signature to ctypes arrays
    pk_buf = (c_ubyte * len(pk))(*pk)
    pk_len = c_ulong(len(pk))

    data_buf = (c_ubyte * len(data))(*data)
    data_len = c_ulong(len(data))

    sig_buf = (c_ubyte * len(sig))(*sig)
    sig_len = c_ulong(len(sig))

    # Call the C function
    rv = ep11.m_VerifySingle(
        cast(pk_buf, POINTER(c_ubyte)), pk_len,
        byref(mech_struct),
        cast(data_buf, POINTER(c_ubyte)), data_len,
        cast(sig_buf, POINTER(c_ubyte)), sig_len,
        target
    )

    # Check return value
    if rv == 0:
        return None
    else:
        return toError(rv)

############################################################################################
############################################################################################

def GenerateRandom(target, length):
    # Allocate memory for the random bytes (create a buffer of the required length)
    random_data = (c_ubyte * length)()  # Create a ctypes array of unsigned bytes
    # Call the C function to generate random data
    rv = ep11.m_GenerateRandom(random_data, length, target)
    
    # Check return value for success
    if rv != CKR_OK:
        # Here, you would have a function to convert the error code to an exception or error message
        raise Exception(f"Error generating random data: {rv}")
    
    # Convert random data to a Python byte array and return
    return bytearray(random_data)



############################################################################################
############################################################################################

## HsmInit implementation
## Set Single for reenciphering
def HsmInit(input_str):
    rc = ep11.m_init()
    if rc != XCP_OK:
        print("pyep11 init error", file=sys.stderr)
        sys.exit(1)

    target = XCP_TGT_INIT
    module = XCP_Module()
    module.version = XCP_MOD_VERSION

    pairs = input_str.strip().split()
    use_virtual = len(pairs) > 1

    for pair in pairs:
        if '.' not in pair:
            print(f"Invalid format: {pair}")
            continue
        try:
            adapter, domain = map(int, pair.split('.'))
        except ValueError:
            print(f"Invalid numbers in: {pair}")
            continue

        print(f"Initializing adapter {adapter:02d} and domain {domain:02d}")
        module.module_nr = adapter
        for i in range(32):
            module.domainmask[i] = 0
        XCPTGTMASK_SET_DOM(module.domainmask, domain)
        if use_virtual:
            module.flags |= XCP_MFL_VIRTUAL | XCP_MFL_PROBE | XCP_MFL_MODULE
        else:
            module.flags |=  XCP_MFL_PROBE | XCP_MFL_MODULE

        #dump_module(module)
        rc = ep11.m_add_module(byref(module), byref(target))
        if rc != CKR_OK:
            print(toError(rc))
            sys.exit(1)

    hex_string = os.getenv("EP11LOGIN")
    if hex_string:
        try:
            blob = binascii.unhexlify(hex_string)
            SetLoginBlob(blob)
        except Exception as e:
            print("Failed to decode pyep11 login blob string:", e)

    return target

############################################################################################
############################################################################################

def Reencipher(target, Key):
    domain_info = CK_IBM_DOMAIN_INFO()
    domain_info_len = c_ulong(ctypes.sizeof(domain_info))

    rv = ep11.m_get_xcp_info(
        cast(ctypes.pointer(domain_info), c_void_p),
        byref(domain_info_len),
        CK_IBM_XCPQ_DOMAIN,
        0,
        target
    )
    if rv != CKR_OK:
        print(f"Failed to query domain info m_get_xcp_info rc: 0x{rv:x}")
        return None, toError(rv)

    rb = XCPadmresp(domain=domain_info.domain)
    lrb = XCPadmresp(domain=domain_info.domain)

    req = bytearray(MAX_BLOB_SIZE)
    CK_BYTE_PTR = ctypes.POINTER(ctypes.c_ubyte)

    req_ptr = cast((ctypes.c_ubyte * MAX_BLOB_SIZE).from_buffer(req), CK_BYTE_PTR)

    resp = bytearray(MAX_BLOB_SIZE)
    resp_ptr = cast((ctypes.c_ubyte * MAX_BLOB_SIZE).from_buffer(resp), CK_BYTE_PTR)
    resp_len = c_ulong(len(resp))

    key_ptr = cast((ctypes.c_ubyte * len(Key)).from_buffer_copy(Key), CK_BYTE_PTR)
    key_len = c_ulong(len(Key))

    req_len = ep11.xcpa_cmdblock(
        req_ptr,
        MAX_BLOB_SIZE,
        XCP_ADM_REENCRYPT,
        byref(rb),
        None,
        key_ptr,
        key_len
    )
    if req_len < 0:
        return None, toError(CKR_FUNCTION_FAILED)

    rc = c_ulong(0)
    zero = c_ulong(0)
    result = ep11.m_admin(
        resp_ptr, byref(resp_len),
        None, byref(zero),
        req_ptr, c_ulong(req_len),
        None, 0, target
    )
    if result != CKR_OK or resp_len.value == 0:
        print(f"reencryption failed: {result} {resp_len.value}")
        return None, toError(result)

    if ep11.xcpa_internal_rv(resp_ptr, resp_len, byref(lrb), byref(rc)) < 0:
        print(f"reencryption response malformed: 0x{rc.value:x}")
        return None, toError(CKR_FUNCTION_FAILED)

    if key_len.value != lrb.pllen:
        print(f"Blob size changed. Old: 0x{key_len.value:x}, New: 0x{lrb.pllen:x}")
        return None, toError(CKR_FUNCTION_FAILED)

    return ctypes.string_at(lrb.payload, lrb.pllen), None


############################################################################################
############################################################################################

def GetMechanismList(target):
    counter = c_ulong(0)

    # First call to get the size of the mechanism list
    rv = ep11.m_GetMechanismList(
        c_ulong(0),  # CK_SLOT_ID = 0
        None,
        byref(counter),
        target
    )
    if rv != CKR_OK:
        return "", toError(rv)

    count = counter.value
    mech_array_type = CK_MECHANISM_TYPE * count

    # Allocate array for mechanisms
    mlist = mech_array_type()
    
    # Second call to get the actual mechanism list
    rv = ep11.m_GetMechanismList(
        c_ulong(0),
        mlist,
        byref(counter),
        target
    )
    if rv != CKR_OK:
        return "", toError(rv)

    # Assuming you have a dictionary mapping values to names
    result = []
    for i in range(counter.value):
        mech_val = mlist[i]
        name = MechToName.get(mech_val, f"UNKNOWN({mech_val})")
        result.append(name)

    return " ".join(result), None

############################################################################################
############################################################################################

def WrapKey(target, mechanism, kek, key):    

    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0

    if kek:
        kek_buf = (c_ubyte * len(kek))(*kek)
        kekC = cast(kek_buf, POINTER(c_ubyte))
        kekLenC = c_ulong(len(kek))
    else:
        kekC = None
        LenC = c_ulong(0)

    if key:
        key_buf = (c_ubyte * len(key))(*key)
        keyC = cast(key_buf, POINTER(c_ubyte))
        keyLenC = c_ulong(len(key))
    else:
        keyC = None
        LenC = c_ulong(0)

     # Prepare wrappedKeynature buffer
    wrappedKey = create_string_buffer(MAX_BLOB_SIZE)
    wrappedKeyC = cast(wrappedKey, POINTER(c_ubyte))
    wrappedKeyLenC = c_ulong(MAX_BLOB_SIZE)

    rv = ep11.m_WrapKey(keyC, keyLenC, kekC, kekLenC, None, 0 , byref(mech_struct), wrappedKeyC, byref(wrappedKeyLenC), target)

    if rv != CKR_OK:
        e1 = toError(rv)
        return None, e1

    # Resize the cipher array based on the returned cipher length
    wrappedKey = wrappedKey[:wrappedKeyLenC.value]
    return wrappedKey, None

############################################################################################
############################################################################################

def UnwrapKey(target, mechanism, kek, key, attr):  
    mecharena = Arena()
    mech_struct = CK_MECHANISM()
    mech_struct.mechanism = c_ulong(mechanism.Mechanism)

    attrarena, t, tcount = convert_attributes_to_ck(attr)

    if mechanism.Parameter:
        buf_ptr, buf_len = mecharena.allocate(mechanism.Parameter)
        mech_struct.pParameter = buf_ptr
        mech_struct.ulParameterLen = buf_len
    else:
        mech_struct.pParameter = None
        mech_struct.ulParameterLen = 0

    if kek:
        kek_buf = (c_ubyte * len(kek))(*kek)
        kekC = cast(kek_buf, POINTER(c_ubyte))
        kekLenC = c_ulong(len(kek))
    else:
        kekC = None
        LenC = c_ulong(0)

    if key:
        key_buf = (c_ubyte * len(key))(*key)
        keyC = cast(key_buf, POINTER(c_ubyte))
        keyLenC = c_ulong(len(key))
    else:
        keyC = None
        LenC = c_ulong(0)

     # Prepare wrappedKeynature buffer
    unwrappedKey = create_string_buffer(MAX_BLOB_SIZE)
    unwrappedKeyC = cast(unwrappedKey, POINTER(c_ubyte))
    unwrappedKeyLenC = c_ulong(MAX_BLOB_SIZE)

    # Prepare wrappedKeynature buffer
    cSum = create_string_buffer(MAX_CSUMSIZE)
    cSumC = cast(cSum, POINTER(c_ubyte))
    cSumLenC = c_ulong(MAX_CSUMSIZE)

    rv = ep11.m_UnwrapKey(keyC, keyLenC, kekC, kekLenC, None, 0, LoginBlob, LoginBlobLen, byref(mech_struct), t, tcount, unwrappedKeyC, byref(unwrappedKeyLenC), cSumC, byref(cSumLenC), target)
    if rv != CKR_OK:
        e1 = toError(rv)
        return None, None,e1

    # Resize the cipher array based on the returned cipher length
    unwrappedKey = unwrappedKey[:unwrappedKeyLenC.value]
    cSum = cSum[:cSumLenC.value]
    return unwrappedKey, cSum, None

############################################################################################
############################################################################################
CK_ULONG = ctypes.c_ulong
CK_RSA_PKCS_MGF_TYPE = CK_ULONG                 # alias
CK_RSA_PKCS_OAEP_SOURCE_TYPE = CK_ULONG 
CK_VOID_PTR  = ctypes.c_void_p 

# Define CK_RSA_PKCS_OAEP_PARAMS in Python
class CK_RSA_PKCS_OAEP_PARAMS(ctypes.Structure):
    _fields_ = [
        ("hashAlg", CK_MECHANISM_TYPE),
        ("mgf", CK_RSA_PKCS_MGF_TYPE),
        ("source", CK_RSA_PKCS_OAEP_SOURCE_TYPE),
        ("pSourceData", CK_VOID_PTR),
        ("ulSourceDataLen", CK_ULONG),
    ]


def NewOAEPParams(hash_alg: int, mgf: int, source_type: int, source_data: bytes):
    params = CK_RSA_PKCS_OAEP_PARAMS()

    params.hashAlg = CK_MECHANISM_TYPE(hash_alg)
    params.mgf = CK_RSA_PKCS_MGF_TYPE(mgf)
    params.source = CK_RSA_PKCS_OAEP_SOURCE_TYPE(source_type)

    if not source_data:
        # No source data
        params.pSourceData = CK_VOID_PTR(None)
        params.ulSourceDataLen = CK_ULONG(0)
    else:
        # Allocate a buffer for the source data
        buf = ctypes.create_string_buffer(source_data)
        params.pSourceData = ctypes.cast(buf, CK_VOID_PTR)
        params.ulSourceDataLen = CK_ULONG(len(source_data))

        # Important: keep buffer alive by attaching to object
        params._source_buf = buf

    # Return raw bytes like Go's memBytes()
    size = ctypes.sizeof(params)
    return bytes(ctypes.string_at(ctypes.byref(params), size))
