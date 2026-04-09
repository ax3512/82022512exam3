# -*- coding: utf-8 -*-
"""임베딩 모델 다운로드 — SSL 인증서 우회."""
import os
import ssl

# SSL 검증 비활성화
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"

# httpx SSL 우회 (monkey-patch)
import httpx
_OrigClient = httpx.Client
_OrigAsyncClient = httpx.AsyncClient

class _NoVerifyClient(_OrigClient):
    def __init__(self, *args, **kwargs):
        kwargs["verify"] = False
        super().__init__(*args, **kwargs)

class _NoVerifyAsyncClient(_OrigAsyncClient):
    def __init__(self, *args, **kwargs):
        kwargs["verify"] = False
        super().__init__(*args, **kwargs)

httpx.Client = _NoVerifyClient
httpx.AsyncClient = _NoVerifyAsyncClient

# urllib3 경고 끄기
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass

# 모델 다운로드
print("임베딩 모델 다운로드 시작 (약 4GB)...")
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "intfloat/multilingual-e5-large",
    cache_folder="./models/multilingual-e5-large",
    device="cpu",
)
dim = model.get_sentence_embedding_dimension()
print(f"OK {dim}")
print("모델 다운로드 완료!")
