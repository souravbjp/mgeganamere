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

def encrypt_key(a, key):
    return sum((aes_cbc_encrypt_a32(a[i:i+4], key) for i in range(0, len(a), 4)), ())

def decrypt_key(a, key):
    return sum((aes_cbc_decrypt_a32(a[i:i+4], key) for i in range(0, len(a), 4)), ())

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

def stringhash(s, aeskey):
    s32 = str_to_a32(s.encode('utf-8'))
    h32 = [0, 0, 0, 0]
    for i in range(len(s32)):
        h32[i % 4] ^= s32[i]
    for _ in range(0x4000):
        h32 = list(aes_cbc_encrypt_a32(h32, aeskey))
    return a32_to_base64((h32[0], h32[2]))

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

    def login(self, email=None, password=None):
        if email and password:
            self._login_user(email.lower().strip(), password)
        else:
            self._login_anonymous()
        return self

    def _login_user(self, email, password):
        resp0 = self._api_request({'a': 'us0', 'user': email})

        if isinstance(resp0, dict) and resp0.get('v') == 2:
            import hashlib
            salt         = base64_url_decode(resp0['s'])
            dk           = hashlib.pbkdf2_hmac('sha512', password.encode(), salt, 100000, 32)
            password_key = str_to_a32(dk[:16])
            uh           = base64_url_encode(dk[16:])
        else:
            password_key = prepare_key(str_to_a32(password.encode('utf-8')))
            uh           = stringhash(email, password_key)

        resp = self._api_request({'a': 'us', 'user': email, 'uh': uh})
        if isinstance(resp, int):
            raise Exception(f"Login failed, error code: {resp}")
        self._process_login_response(resp, password_key)

    def _login_anonymous(self):
        master_key   = [random.randint(0, 0xFFFFFFFF)] * 4
        password_key = [random.randint(0, 0xFFFFFFFF)] * 4
        session_key  = [random.randint(0, 0xFFFFFFFF)] * 4
        user = self._api_request({
            'a': 'up',
            'k': a32_to_base64(encrypt_key(master_key, password_key)),
            'ts': base64_url_encode(
                a32_to_str(session_key) +
                a32_to_str(encrypt_key(session_key, master_key))
            )
        })
        resp = self._api_request({'a': 'us', 'user': user})
        self._process_login_response(resp, password_key)

    def _process_login_response(self, resp, password_key):
        self.master_key = decrypt_key(base64_to_a32(resp['k']), password_key)

        if 'tsid' in resp:
            tsid = base64_url_decode(resp['tsid'])
            if a32_to_str(encrypt_key(str_to_a32(tsid[:16]), self.master_key)) == tsid[-16:]:
                self.sid = resp['tsid']

        elif 'csid' in resp:
            privk_a32 = decrypt_key(base64_to_a32(resp['privk']), self.master_key)
            buf       = a32_to_str(privk_a32)
            comps     = []
            for _ in range(4):
                if len(buf) < 2:
                    break
                blen = (buf[0] << 8) | buf[1]
                blen = (blen + 7) // 8
                comps.append(int.from_bytes(buf[2:2+blen], 'big'))
                buf = buf[2+blen:]

            if len(comps) < 3:
                raise Exception("RSA private key parse failed")

            p, q, d = comps[0], comps[1], comps[2]
            n, e    = p * q, 65537
            if (e * d) % ((p-1)*(q-1)) != 1:
                d = pow(e, -1, (p-1)*(q-1))

            rsa     = RSA.construct((n, e, d, p, q))
            sid_int = rsa._decrypt(mpi_to_int(base64_url_decode(resp['csid'])))
            sid_hex = format(sid_int, 'x')
            if len(sid_hex) % 2:
                sid_hex = '0' + sid_hex
            self.sid = base64_url_encode(binascii.unhexlify(sid_hex)[:43])
        else:
            raise Exception("No session token in login response")

    def _api_request(self, data):
        params  = {'id': self.sequence_num}
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
                    if resp == -15 and attempt < 3:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise Exception(f"MEGA API error: {resp}")
                return resp
            except Exception as e:
                if 'MEGA API error' in str(e):
                    raise
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def get_files(self):
        resp = self._api_request({'a': 'f', 'c': 1, 'r': 1})
        return self._parse_file_list(resp)

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
                k = decrypt_key(base64_to_a32(f['k'].split(':')[-1]), self.master_key)
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

    def rename(self, file_node, new_name):
        if not isinstance(file_node, dict):
            raise ValueError("file_node must be a dict from get_files()")
        key = file_node.get('key')
        if key is None:
            raise Exception("File has no decrypted key")
        enc_attr = encrypt_attr({'n': new_name}, key)
        return self._api_request({
            'a': 'a',
            'attr': base64_url_encode(enc_attr),
            'key': a32_to_base64(encrypt_key(key, self.master_key)),
            'n': file_node['h'],
            'i': make_id(10)
        })
