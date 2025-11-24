- [【Phase 2】 オフライン検証 (Stateless Validation)](#phase-2-オフライン検証-stateless-validation)
  - [🎯 学習目標](#-学習目標)
  - [📚 PDF参照](#-pdf参照)
  - [🛠 1. ライブラリの確認](#-1-ライブラリの確認)
  - [🛠 2. APIサーバーの実装 (`api/server.py`)](#-2-apiサーバーの実装-apiserverpy)
  - [🚀 3. 実践ステップ (動作確認)](#-3-実践ステップ-動作確認)
  - [コマンドメモ](#コマンドメモ)
- [💡 技術解説: オフライン検証の仕組み](#-技術解説-オフライン検証の仕組み)
  - [Industry Mapping (AWS/Oktaとの比較)](#industry-mapping-awsoktaとの比較)
  - [⚠️ 重要な注意点: Audience (aud) について](#️-重要な注意点-audience-aud-について)

### 【Phase 2】 オフライン検証 (Stateless Validation)

#### 🎯 学習目標

APIサーバーがKeycloakに毎回問い合わせるのをやめ、**「暗号技術（署名検証）」** を使って自律的にトークンの正当性を判断できるようにします。

  * **JWT (JSON Web Token):** トークン自体にデータ（Payload）と署名（Signature）が含まれている構造を理解します。
  * **JWKS (JSON Web Key Set):** 署名を検証するための「公開鍵」をKeycloakから取得する仕組みを学びます。
  * **Industry Mapping:**
      * **AWS Cognito / Auth0 / Okta:** すべてこの方式が標準です。各社が提供するSDK（例: `aws-jwt-verify`）は、裏で今回実装するロジック（JWKS取得→署名検証→クレーム確認）を行っています。
      * **メリット:** Keycloakがダウンしていても（鍵がキャッシュされていれば）認証を継続できる「疎結合」な構成になります。また、通信回数が減るため**レイテンシが大幅に改善**します。

#### 📚 PDF参照

  * **Chapter 3: Brief Introduction to Standards**
      * [cite\_start]"Leveraging JWT for tokens": JWTの構造 (Header, Payload, Signature) [cite: 417]。
      * [cite\_start]JWK (JSON Web Key) と JWKS の役割 [cite: 419]。
      * [cite\_start]JWT検証のステップ（JWKS取得、公開鍵による署名検証）[cite: 421, 422]。
  * **Chapter 5: Authorizing Access with OAuth 2.0**
      * [cite\_start]"Validating access tokens": 直接トークンを検証する方法 [cite: 839]。

-----

#### 🛠 1. ライブラリの確認

今回は `PyJWT` というライブラリを使用します。`api/Dockerfile` または環境を確認し、インストールされていることを確認してください。
※ 以前の申し送り事項によれば `PyJWT[crypto]` がインストール済みとのことですので、そのまま進めます。

#### 🛠 2. APIサーバーの実装 (`api/server.py`)

`server.py` を以下の内容で完全に書き換えてください。
イントロスペクション（`requests.post`）の代わりに、公開鍵による検証ロジックを実装します。

**ファイル:** `api/server.py`

```python
from flask import Flask, request, jsonify
import jwt
from jwt import PyJWKClient
import os
import logging
import sys

# 1. ロギングの設定
# 標準出力(stdout)へログを出し、Dockerログとして拾えるようにする
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 2. 設定値の取得
KEYCLOAK_INTERNAL_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080")
REALM_NAME = os.environ.get("REALM_NAME", "demo-realm")

# ★重要: ここの値がログに出力される "iss" と一致しているか確認します
EXPECTED_ISSUER = "http://keycloak:8080/realms/demo-realm"
EXPECTED_AUDIENCE = "account"

JWKS_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{REALM_NAME}/protocol/openid-connect/certs"
jwks_client = PyJWKClient(JWKS_URL)

def verify_token_offline(token):
    """
    ログ出力を強化した検証ロジック
    """
    try:
        # A. 検証なしでペイロードの中身を確認 (デバッグ用)
        # verify_signature=False にすることで、署名が不正でも中身だけは見れる
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        logger.debug(f"--- DEBUG: Payload (Unverified) ---\n{unverified_payload}\n--------------------------------")

        # B. 署名鍵の取得
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # C. 正規の検証
        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=EXPECTED_ISSUER,
            audience=EXPECTED_AUDIENCE,
            options={"verify_aud": False}
        )
        return data

    # --- エラーハンドリング (詳細をログに出す) ---
    except jwt.ExpiredSignatureError:
        logger.error("Validation Error: Token has expired (有効期限切れ)")
    except jwt.InvalidIssuerError as e:
        # 期待値と実際の値をログに出すのがトラブルシュートの鍵
        logger.error(f"Validation Error: Invalid Issuer.\n  Expected: {EXPECTED_ISSUER}\n  But got error: {e}")
    except jwt.InvalidAudienceError:
        logger.error("Validation Error: Invalid Audience (オーディエンス不一致)")
    except jwt.InvalidSignatureError:
        logger.error("Validation Error: Invalid Signature (署名検証失敗 - 鍵の不一致)")
    except jwt.PyJWTError as e:
        logger.error(f"Validation Error: Generic PyJWT Error: {e}")
    except Exception as e:
        logger.error(f"Validation Error: Unexpected Error: {e}")
    
    return None

@app.route('/secure')
def secure():
    auth_header = request.headers.get('Authorization', None)
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401

    parts = auth_header.split()
    if parts[0].lower() != 'bearer' or len(parts) != 2:
        return jsonify({"error": "Invalid Header Format"}), 401

    access_token = parts[1]

    # 検証実行
    token_payload = verify_token_offline(access_token)

    if not token_payload:
        return jsonify({"error": "Token is invalid or expired"}), 401

    return jsonify({
        "message": "Access Granted via Offline Validation!",
        "user": token_payload.get('preferred_username'),
        "iss": token_payload.get('iss')
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

**変更を反映:**

```bash
docker-compose restart api
```

-----

#### 🚀 3. 実践ステップ (動作確認)

Phase 1 と同じ手順で確認しますが、裏側の仕組みが全く異なります。

**Step 1: アクセストークンの取得**
前回と同じコマンドです。`Host` ヘッダーの指定を忘れずに。

```bash
export TOKEN=$(curl -s -X POST 'http://localhost:8080/realms/demo-realm/protocol/openid-connect/token' \
  -H 'Host: keycloak:8080' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=demo-client' \
  -d 'client_secret=bABIT6UsHLd1TjwXzsx5YXmbEoaboZl1' \
  -d 'grant_type=client_credentials' | jq -r .access_token)
```

> ※ `client_secret` はご自身の環境の値に合わせてください。

**Step 2: APIサーバーへアクセス**

```bash
curl http://localhost:5000/secure -H "Authorization: Bearer $TOKEN"
```

**成功時のレスポンス例:**

```json
{
  "iss": "http://localhost:8080/realms/demo-realm",
  "message": "Access Granted via Offline Validation!",
  "scope": "email profile",
  "user": "service-account-demo-client",
  "validation_method": "stateless (public key)"
}
```

#### コマンドメモ

- apiコンテナーの設定値取り込みを迅速にするためのコマンドメモ

```bash
docker compose down api
docker compose up api --build -d
```

-----

### 💡 技術解説: オフライン検証の仕組み

今回の実装では、APIサーバーはリクエストのたびにKeycloakへアクセスしていません。

1.  **JWKSの取得 (初回のみ):** `PyJWKClient` が起動時（または必要時）に `http://keycloak:8080/.../certs` にアクセスし、公開鍵リストをダウンロードしてメモリにキャッシュします。
2.  **計算による検証:** 送られてきたトークンの署名部分を、キャッシュした公開鍵を使って数学的に検証します。これが成功すれば、トークンは「改ざんされていない」かつ「Keycloakが発行した」ことが保証されます。
3.  **クレームの検証:** トークンの中身（JSON）を見て、有効期限(`exp`)や発行者(`iss`)が期待通りかをチェックします。

#### Industry Mapping (AWS/Oktaとの比較)

  * **AWS Cognito:** `https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json` から鍵を取得します。
  * **Keycloak:** `.../protocol/openid-connect/certs` から取得します。URLの構造が違うだけで、やっていることは全く同じです。

#### ⚠️ 重要な注意点: Audience (aud) について

コード内で `options={"verify_aud": False}` としている点に注目してください。
本来、OAuth 2.0 では「このトークンは誰（どのAPI）のために発行されたか」を示す `aud` クレームの検証が必須です。
しかし、Keycloakのデフォルト設定では、アクセストークンの `aud` には `account`（アカウント管理クライアント）しか含まれないことが多く、自作した `demo-client` のIDが含まれない場合があります。

  * **本番環境での対応:** Keycloak側で **Mapper** を設定し、アクセストークンの `aud` にAPIのリソースIDが含まれるように設定してから、`verify_aud: True` にするのが正しい実装です。
