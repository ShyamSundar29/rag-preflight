# Tokenizer cache for restricted networks

The reference applications use `tiktoken` to count the exact inputs sent to
`text-embedding-3-small` and to keep chunks within the configured token limit.
The Python package does not contain the `cl100k_base` data file. On first use,
`tiktoken` retrieves it from:

`https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken`

This happens during `verify-papers` and `dry-run` as well as live ingestion. It
does not call the OpenAI API or consume API credit. A firewall or corporate proxy
may block the tokenizer host even when package installation succeeded.

The applications now convert that failure into a concise error containing the
host, expected digest, destination and `TIKTOKEN_CACHE_DIR`. To prepare the cache
on a network-enabled approved machine:

```sh
mkdir -p /approved/path/tiktoken-cache
curl -fL \
  https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken \
  -o /approved/path/tiktoken-cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4
shasum -a 256 /approved/path/tiktoken-cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4
```

The expected SHA-256 is:

`223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`

Transfer that verified file through the organization’s approved process. On the
restricted machine:

```sh
export TIKTOKEN_CACHE_DIR=/approved/path/tiktoken-cache
```

Then rerun `verify-papers` or `dry-run`. The cache key is the SHA-1 of the source
URL, which is the filename `tiktoken` expects. Do not rename an arbitrary file or
skip the SHA-256 check. A different future embedding model may use a different
encoding artifact; follow the error emitted for that model rather than reusing
this file blindly.
