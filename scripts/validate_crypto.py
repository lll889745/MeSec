import os
from typing import Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def encrypt(plaintext: bytes, key: bytes) -> Tuple[bytes, bytes, bytes]:
    """Encrypt a plaintext with AES-256-GCM, returning nonce, ciphertext, and tag."""
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    return nonce, ciphertext, encryptor.tag


def decrypt(nonce: bytes, ciphertext: bytes, tag: bytes, key: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def main() -> None:
    key = os.urandom(32)
    original_message = "\u8fd9\u662f\u6211\u7684\u79d8\u5bc6\u4fe1\u606f"
    plaintext = original_message.encode("utf-8")

    nonce, ciphertext, tag = encrypt(plaintext, key)
    recovered = decrypt(nonce, ciphertext, tag, key)

    print("原始信息:", original_message)
    print("解密结果:", recovered.decode("utf-8"))
    print("解密是否匹配:", recovered == plaintext)

    try:
        wrong_key = os.urandom(32)
        decrypt(nonce, ciphertext, tag, wrong_key)
    except InvalidTag:
        print("使用错误密钥解密时捕获 InvalidTag 异常，验证通过。")
    else:
        print("警告：错误密钥解密未触发 InvalidTag，需检查实现。")


if __name__ == "__main__":
    main()
