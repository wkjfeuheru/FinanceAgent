# Encryption

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/encryption/Encryption)

Add custom at-rest encryption to your LangGraph application.

.. warning::
    This API is in beta and may change in future versions.

The Encryption class provides a system for implementing custom encryption
of data at rest in LangGraph applications. It supports encryption of
both opaque blobs (like checkpoints) and structured JSON data (like
metadata, context, kwargs, values, etc.).

To use, create a separate Python file and add the path to the file to your
LangGraph API configuration file (`langgraph.json`). Within that file, create
an instance of the Encryption class and register encryption and decryption
handlers as needed.

Example `langgraph.json` file:

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./my_agent/agent.py:graph"
  },
  "env": ".env",
  "encryption": {
    "path": "./encryption.py:my_encryption"
  }
}
```

Then the LangGraph server will load your encryption file and use it to
encrypt/decrypt data at rest.

!!! warning "JSON Encryptors Must Preserve Keys"

    JSON encryptors **must not add or remove keys** from the input dict.
    Only values may be transformed. This constraint is **enforced at runtime
    by the server** and exists because SQL JSONB merge operations (used for
    partial updates) work at the key level.

    **Correct (per-key encryption):**
    ```python
    # Input:  {"secret": "value", "plain": "x"}
    # Output: {"secret": "<encrypted>", "plain": "x"}  ✓ Keys preserved
    ```

    **Incorrect (key consolidation):**
    ```python
    # Input:  {"secret": "value", "plain": "x"}
    # Output: {"__encrypted__": "<blob>", "plain": "x"}  ✗ Key changed
    ```

    If your encryptor needs to store auxiliary data (DEK, IV, etc.), embed it
    within the encrypted value itself, not as separate keys.

???+ example "Basic Usage"

    ```python
    from langgraph_sdk import Encryption, EncryptionContext

    my_encryption = Encryption()

    SKIP_FIELDS = {"tenant_id", "owner", "thread_id", "assistant_id"}
    ENCRYPTED_PREFIX = "encrypted:"

    @my_encryption.encrypt.blob
    async def encrypt_blob(ctx: EncryptionContext, blob: bytes) -> bytes:
        return your_encrypt_bytes(blob)

    @my_encryption.decrypt.blob
    async def decrypt_blob(ctx: EncryptionContext, blob: bytes) -> bytes:
        return your_decrypt_bytes(blob)

    @my_encryption.encrypt.json
    async def encrypt_json(ctx: EncryptionContext, data: dict) -> dict:
        result = {}
        for k, v in data.items():
            if k in SKIP_FIELDS or v is None:
                result[k] = v
            else:
                result[k] = ENCRYPTED_PREFIX + your_encrypt_string(v)
        return result

    @my_encryption.decrypt.json
    async def decrypt_json(ctx: EncryptionContext, data: dict) -> dict:
        result = {}
        for k, v in data.items():
            if isinstance(v, str) and v.startswith(ENCRYPTED_PREFIX):
                result[k] = your_decrypt_string(v[len(ENCRYPTED_PREFIX):])
            else:
                result[k] = v
        return result
    ```

???+ example "Field-Specific Logic"

    The `ctx.model` and `ctx.field` attributes tell you which model type and
    specific field is being encrypted, allowing different logic:

    ```python
    @my_encryption.encrypt.json
    async def encrypt_json(ctx: EncryptionContext, data: dict) -> dict:
        if ctx.field == "metadata":
            # Metadata - standard encryption
            return encrypt_standard(data)
        elif ctx.field == "values":
            # Thread values - more sensitive, use stronger encryption
            return encrypt_sensitive(data)
        else:
            return encrypt_standard(data)
    ```

    !!! warning "Model/Field May Differ Between Encrypt and Decrypt"

        Data encrypted with one `(model, field)` pair is **not guaranteed**
        to be decrypted with the same pair. The server performs SQL JSONB
        merges that can move encrypted values between models (e.g., cron
        metadata → run metadata). Your decryption logic must handle data
        regardless of the `ctx.model` or `ctx.field` values at decrypt time.

        **Safe:** Use `ctx.model`/`ctx.field` for logging or metrics only.

        **Safe:** Encrypt different keys based on `ctx.field`, but use a
        single decrypt handler that decrypts any value with the encrypted
        prefix (and passes through plaintext unchanged):

        ```python
        ENCRYPTED_PREFIX = "enc:"

        @my_encryption.encrypt.json
        async def encrypt_json(ctx: EncryptionContext, data: dict) -> dict:
            # Encrypt different keys depending on the field
            if ctx.field == "context":
                keys_to_encrypt = {"api_key", "secret_token"}
            else:
                keys_to_encrypt = {"email", "ssn"}
            return {
                k: ENCRYPTED_PREFIX + encrypt(v) if k in keys_to_encrypt else v
                for k, v in data.items()
            }

        @my_encryption.decrypt.json
        async def decrypt_json(ctx: EncryptionContext, data: dict) -> dict:
            # Decrypt ANY value with the prefix, regardless of model/field
            return {
                k: decrypt(v[len(ENCRYPTED_PREFIX):])
                   if isinstance(v, str) and v.startswith(ENCRYPTED_PREFIX)
                   else v
                for k, v in data.items()
            }
        ```

        **Unsafe:** Using different encryption keys or algorithms based on
        `ctx.model`/`ctx.field` will cause decryption failures.

## Signature

```python
Encryption(
    self,
)
```

## Constructors

```python
__init__(
    self,
) -> None
```


## Properties

- `types`
- `encrypt`
- `decrypt`

## Methods

- [`context()`](https://reference.langchain.com/python/langgraph-sdk/encryption/Encryption/context)
- [`get_json_encryptor()`](https://reference.langchain.com/python/langgraph-sdk/encryption/Encryption/get_json_encryptor)
- [`get_json_decryptor()`](https://reference.langchain.com/python/langgraph-sdk/encryption/Encryption/get_json_decryptor)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/encryption/__init__.py#L201)