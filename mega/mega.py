import re
import json
import time
import random
import struct
import binascii
import requests
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA


def a32_to_str(a):
    return struct.pack('>%dI' % len(a), *a)

def str_to_a32(b):
    if isinstance(b, str):
        b = b.encode('latin-1')
    if len(b) % 4:
        b += b'\x00' * (4 - len(b) % 4)
    return struct.unpack('>%dI' % (len(b) // 4), b)

def base64_url_encode(data):
    import base64
    if isinstance(data, str):
        data = data.encode('latin-1')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def base64_url_decode(data):
    import base64
    if isinstance(data, bytes):
        data = data.decode('ascii')
    data += '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data)

def a32_to_base64(a):
    return base64_url_encode(a32_to_str(a))

def base64_to_a32(s):
    return str_to_a32(base64_url_decode(s))

def mpi_to_int(s):
    if isinstance(s, str):
        s = s.encode('latin-1')
    return int.from_bytes(s[2:], 'big')

def aes_cbc_encrypt(data, key):
    return AES.new(key, AES.MODE_CBC, b'\x00'*16).encrypt(data)

def aes_cbc_decrypt(data, key):
    return AES.new(key, AES.MODE_CBC, b'\x00'*16).decrypt(data)

def aes_cbc_encrypt_a32(data, key):
    return str_to_a32(aes_cbc_encrypt(a32_to_str(data), a32_to_str(key)))

def aes_cbc_decrypt_a32(data, key):
    return str_to_a32(aes_cbc_decrypt(a32_to_str(data), a32_to_str(key)))

def stringhash(s, aeskey):
    s32 = str_to_a32(s.encode('utf-8'))
    h32 = [0, 0, 0, 0]
    for i in range(len(s32)):
        h32[i % 4] ^= s32[i]
    for _ in range(0x4000):
        h32 = list(aes_cbc_encrypt_a32(h32, aeskey))
    return a32_to_base64((h32[0], h32[2]))

def prepare_key(a):
    pkey = [0x93C467E3, 0x7DB0C7A4, 0xD1BE3F81, 0x0152CB56]
    for _ in range(0x10000):
        for j in range(0, len(a), 4):
            key = [0, 0, 0, 0]
            for i in range(4):
                if i + j < len(a):
                    key[i] = a[i + j]
            pkey = list(aes_cbc_encrypt_a32(pkey, key))
    return pkey

def encrypt_key(a, key):
    return sum((aes_cbc_encrypt_a32(a[i:i+4], key) for i in range(0, len(a), 4)), ())

def decrypt_key(a, key):
    return sum((aes_cbc_decrypt_a32(a[i:i+4], key) for i in range(0, len(a), 4)), ())

def decrypt_attr(attr, key):
    attr = aes_cbc_decrypt(attr, a32_to_str(key))
    attr = attr.rstrip(b'\x00')
    try:
        m = re.search(b'MEGA(.+)', attr)
        if m:
            return json.loads(m.group(1).decode('utf-8'))
    except Exception:
        pass
    return False

def encrypt_attr(attr, key):
    attr = b'MEGA' + json.dumps(attr).encode('utf-8')
    if len(attr) % 16:
        attr += b'\x00' * (16 - len(attr) % 16)
    return aes_cbc_encrypt(attr, a32_to_str(key))

def make_id(length=10):
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    return ''.join(random.choice(chars) for _ in range(length))


class Mega:
    def __init__(self):
        self.schema       = 'https'
        self.domain       = 'g.api.mega.co.nz'
        self.timeout      = 160
        self.sid          = None
        self.master_key   = None
        self.sequence_num = random.randint(0, 0xFFFFFFFF)
        self.session      = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def login(self, email, password):
        email    = email.strip().lower()
        password = password.strip()
        self._login_user(email, password)
        return self

    def get_files(self):
        resp = self._api_request({'a': 'f', 'c': 1, 'r': 1})
        return self._parse_file_list(resp)

    def rename(self, node, new_name):
        key = node.get('key')
        if not key:
            raise Exception("Node has no key")
        attr_key   = key[:4] if len(key) >= 4 else key
        enc_attr   = encrypt_attr({'n': new_name}, attr_key)
        enc_attr64 = base64_url_encode(enc_attr)
        k_enc      = a32_to_base64(encrypt_key(key, self.master_key))
        return self._api_request({
            'a': 'a',
            'attr': enc_attr64,
            'key': k_enc,
            'n': node['h'],
            'i': make_id(10)
        })

    def _login_user(self, email, password):
        uh_resp = self._api_request({'a': 'us0', 'user': email})
        if isinstance(uh_resp, int):
            raise Exception(f"Login pre-check failed: {uh_resp}")

        version = uh_resp.get('v', 1)

        if version == 2:
            import hashlib
            salt         = base64_url_decode(uh_resp['s'])
            dk           = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000, 32)
            password_key = str_to_a32(dk[:16])
            uh           = base64_url_encode(dk[16:])
        else:
            password_key = prepare_key(str_to_a32(password.encode('utf-8')))
            uh           = stringhash(email, password_key)

        resp = self._api_request({'a': 'us', 'user': email, 'uh': uh})
        if isinstance(resp, int):
            raise Exception(f"Authentication failed: {resp}")

        self._process_login_response(resp, password_key)

    def _process_login_response(self, resp, password_key):
        enc_master_key  = base64_to_a32(resp['k'])
        self.master_key = decrypt_key(enc_master_key, password_key)

        if 'tsid' in resp:
            tsid  = base64_url_decode(resp['tsid'])
            check = a32_to_str(encrypt_key(str_to_a32(tsid[:16]), self.master_key))
            if check == tsid[-16:]:
                self.sid = resp['tsid']
            else:
                raise Exception("Session ID verification failed")

        elif 'csid' in resp:
            enc_privk    = base64_to_a32(resp['privk'])
            privk_a32    = decrypt_key(enc_privk, self.master_key)
            privk_bytes  = a32_to_str(privk_a32)

            components = []
            buf = privk_bytes
            for _ in range(4):
                if len(buf) < 2:
                    break
                bit_len  = (buf[0] << 8) | buf[1]
                byte_len = (bit_len + 7) // 8
                val      = int.from_bytes(buf[2:2 + byte_len], 'big')
                components.append(val)
                buf = buf[2 + byte_len:]

            if len(components) < 3:
                raise Exception("Could not parse RSA private key")

            p, q, d = components[0], components[1], components[2]
            n   = p * q
            e   = 65537
            phi = (p - 1) * (q - 1)

            # Verify d; recompute if wrong
            if pow(e, d, phi) != 1:
                d = pow(e, -1, phi)

            rsa_key    = RSA.construct((n, e, d, p, q))
            csid_bytes = base64_url_decode(resp['csid'])
            enc_sid    = mpi_to_int(csid_bytes)
            sid_int    = rsa_key._decrypt(enc_sid)

            sid_hex = format(sid_int, 'x')
            if len(sid_hex) % 2:
                sid_hex = '0' + sid_hex
            sid_bytes  = binascii.unhexlify(sid_hex)
            self.sid   = base64_url_encode(sid_bytes[:43])
        else:
            raise Exception("No session ID in login response")

    def _api_request(self, data):
        params = {'id': self.sequence_num}
        self.sequence_num += 1
        if self.sid:
            params['sid'] = self.sid

        url     = f'{self.schema}://{self.domain}/cs'
        payload = json.dumps([data] if not isinstance(data, list) else data)

        for attempt in range(4):
            try:
                r    = self.session.post(url, params=params, data=payload, timeout=self.timeout)
                resp = r.json()
                if isinstance(resp, list):
                    resp = resp[0]
                if isinstance(resp, int) and resp < 0:
                    raise Exception(f"MEGA API error: {resp}")
                return resp
            except Exception as e:
                if 'MEGA API error' in str(e):
                    raise
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def _parse_file_list(self, data):
        files = {}
        if not isinstance(data, dict) or 'f' not in data:
            return files

        for f in data['f']:
            ftype = f.get('t')
            fid   = f.get('h', '')

            if ftype not in (0, 1) or 'k' not in f:
                files[fid] = f
                continue

            try:
                raw_key  = f['k'].split(':')[-1]
                k        = base64_to_a32(raw_key)
                k        = decrypt_key(k, self.master_key)

                if ftype == 0 and len(k) >= 8:
                    file_key = (k[0]^k[4], k[1]^k[5], k[2]^k[6], k[3]^k[7])
                else:
                    file_key = k[:4] if len(k) >= 4 else k

                attr = decrypt_attr(base64_url_decode(f['a']), file_key)
                if attr:
                    f['a']   = attr
                    f['key'] = file_key
            except Exception:
                pass

            files[fid] = f

        return files
