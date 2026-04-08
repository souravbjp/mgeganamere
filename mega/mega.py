import re
import json
import time
import random
import hashlib
import os
import struct
import binascii
import requests
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Util import Counter

# tenacity ছাড়াই simple retry
def retry_request(func, retries=3, wait=2):
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(wait)


def makebyte(x):
    return codecs_encode(x, 'latin-1') if isinstance(x, str) else x


def a32_to_str(a):
    return struct.pack('>%dI' % len(a), *a)


def str_to_a32(b):
    if isinstance(b, str):
        b = b.encode('latin-1')
    if len(b) % 4:
        b += b'\x00' * (4 - len(b) % 4)
    return struct.unpack('>%dI' % (len(b) // 4), b)


def a32_to_base64(a):
    return base64_url_encode(a32_to_str(a))


def base64_url_encode(data):
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def base64_url_decode(data):
    import base64
    data += '=='
    return base64.urlsafe_b64decode(data.encode('ascii') + b'==')


def base64_to_a32(s):
    return str_to_a32(base64_url_decode(s))


def mpi_to_int(s):
    return int.from_bytes(s[2:], 'big')


def aes_cbc_encrypt(data, key):
    aes_obj = AES.new(key, AES.MODE_CBC, b'\x00' * 16)
    return aes_obj.encrypt(data)


def aes_cbc_decrypt(data, key):
    aes_obj = AES.new(key, AES.MODE_CBC, b'\x00' * 16)
    return aes_obj.decrypt(data)


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
    return sum((aes_cbc_encrypt_a32(a[i:i + 4], key) for i in range(0, len(a), 4)), ())


def decrypt_key(a, key):
    return sum((aes_cbc_decrypt_a32(a[i:i + 4], key) for i in range(0, len(a), 4)), ())


def decrypt_attr(attr, key):
    attr = aes_cbc_decrypt(attr, a32_to_str(key))
    attr = attr.rstrip(b'\x00')
    try:
        return json.loads(re.search(b'MEGA(.+)', attr).group(1).decode('utf-8'))
    except Exception:
        return False


def encrypt_attr(attr, key):
    attr = b'MEGA' + json.dumps(attr).encode('utf-8')
    if len(attr) % 16:
        attr += b'\x00' * (16 - len(attr) % 16)
    return aes_cbc_encrypt(attr, a32_to_str(key))


def make_id(length):
    possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    return ''.join(random.choice(possible) for _ in range(length))


class Mega:
    def __init__(self, options=None):
        self.schema = 'https'
        self.domain = 'mega.co.nz'
        self.timeout = 160
        self.sid = None
        self.sequence_num = random.randint(0, 0xFFFFFFFF)
        self.request_id = make_id(10)
        if options is None:
            options = {}
        self.options = options

    def login(self, email=None, password=None):
        if email:
            return self._login_user(email, password)
        else:
            return self._login_anonymous()

    def _login_anonymous(self):
        master_key = [random.randint(0, 0xFFFFFFFF)] * 4
        password_key = [random.randint(0, 0xFFFFFFFF)] * 4
        session_self_challenge = [random.randint(0, 0xFFFFFFFF)] * 4

        user = self._api_request({
            'a': 'up',
            'k': a32_to_base64(encrypt_key(master_key, password_key)),
            'ts': base64_url_encode(a32_to_str(session_self_challenge) +
                                    a32_to_str(encrypt_key(session_self_challenge, master_key)))
        })

        resp = self._api_request({'a': 'us', 'user': user})
        if isinstance(resp, int):
            raise Exception(f"Login failed with error code: {resp}")

        self._login_process(resp, master_key)
        return self

    def _login_user(self, email, password):
        email = email.lower()
        get_user_salt_resp = self._api_request({'a': 'us0', 'user': email})

        if isinstance(get_user_salt_resp, int):
            raise Exception(f"Login failed with error code: {get_user_salt_resp}")

        if 'v' not in get_user_salt_resp or get_user_salt_resp['v'] != 2:
            password_aes = prepare_key(str_to_a32(password.encode('utf-8')))
            uh = stringhash(email, password_aes)
            resp = self._api_request({'a': 'us', 'user': email, 'uh': uh})
        else:
            import hashlib, hmac, base64
            salt = base64_url_decode(get_user_salt_resp['s'])
            dk = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000, 32)
            password_aes = str_to_a32(dk[:16])
            uh = base64_url_encode(dk[16:])
            resp = self._api_request({'a': 'us', 'user': email, 'uh': uh})

        if isinstance(resp, int):
            raise Exception(f"Login failed with error code: {resp}")

        self._login_process(resp, password_aes)
        return self

    def _login_process(self, resp, password):
        encrypted_master_key = base64_to_a32(resp['k'])
        self.master_key = decrypt_key(encrypted_master_key, password)

        if 'tsid' in resp:
            tsid = base64_url_decode(resp['tsid'])
            key_encrypted = a32_to_str(encrypt_key(str_to_a32(tsid[:16]), self.master_key))
            if key_encrypted == tsid[-16:]:
                self.sid = resp['tsid']
        elif 'csid' in resp:
            encrypted_rsa_private_key = base64_to_a32(resp['privk'])
            rsa_private_key = decrypt_key(encrypted_rsa_private_key, self.master_key)

            private_key = a32_to_str(rsa_private_key)
            rsa_components = []

            for _ in range(4):
                bit_length = (private_key[0] << 8) + private_key[1]
                byte_length = (bit_length + 7) // 8
                component = int.from_bytes(private_key[2:2 + byte_length], 'big')
                rsa_components.append(component)
                private_key = private_key[2 + byte_length:]

            p, q, d, u = rsa_components
            n = p * q

            # e must be a valid public exponent — use standard 65537
            e = 65537

            try:
                rsa_key = RSA.construct((n, e, d, p, q))
            except Exception:
                # fallback: compute d properly
                phi = (p - 1) * (q - 1)
                d = pow(e, -1, phi)
                rsa_key = RSA.construct((n, e, d, p, q))

            encrypted_sid = mpi_to_int(base64_url_decode(resp['csid']))
            decrypted = rsa_key._decrypt(encrypted_sid)
            sid_hex = '%x' % decrypted
            if len(sid_hex) % 2:
                sid_hex = '0' + sid_hex
            sid_bytes = binascii.unhexlify(sid_hex)
            self.sid = base64_url_encode(sid_bytes[:43])

    def _api_request(self, data):
        params = {'id': self.sequence_num}
        self.sequence_num += 1

        if self.sid:
            params['sid'] = self.sid

        if not isinstance(data, list):
            data = [data]

        url = f'{self.schema}://g.api.{self.domain}/cs'
        response = requests.post(
            url,
            params=params,
            data=json.dumps(data),
            timeout=self.timeout
        )
        json_resp = response.json()

        if isinstance(json_resp, list):
            json_resp = json_resp[0]
        if isinstance(json_resp, int) and json_resp < 0:
            raise Exception(f"MEGA API error: {json_resp}")
        return json_resp

    def get_files(self):
        files = self._api_request({'a': 'f', 'c': 1, 'r': 1})
        return self._parse_file_list(files)

    def _parse_file_list(self, files_data):
        files = {}
        if 'f' not in files_data:
            return files

        for f in files_data['f']:
            if f.get('t') in (0, 1) and 'k' in f:
                try:
                    key_str = f['k'].split(':')[-1]
                    k = base64_to_a32(key_str)

                    if f['t'] == 0:
                        k = decrypt_key(k, self.master_key)
                        k = (k[0] ^ k[4], k[1] ^ k[5], k[2] ^ k[6], k[3] ^ k[7])
                    else:
                        k = decrypt_key(k, self.master_key)

                    attr = decrypt_attr(base64_url_decode(f['a']), k[:4] if len(k) >= 4 else k)
                    if attr:
                        f['a'] = attr
                        f['key'] = k
                    files[f['h']] = f
                except Exception:
                    files[f['h']] = f
            else:
                files[f.get('h', '')] = f

        return files

    def rename(self, file, new_name):
        if isinstance(file, dict):
            node = file
        else:
            raise ValueError("file must be a dict node from get_files()")

        key = node.get('key')
        if key is None:
            raise Exception("No key found in node")

        attr_key = key[:4] if len(key) >= 4 else key
        enc_attr = encrypt_attr({'n': new_name}, attr_key)
        enc_attr_b64 = base64_url_encode(enc_attr)

        return self._api_request({
            'a': 'a',
            'attr': enc_attr_b64,
            'key': a32_to_base64(encrypt_key(key, self.master_key)),
            'n': node['h'],
            'i': make_id(10)
        })
