# Keycloak + APIサーバー (Python) 完全コンテナ化ハンズオン

## 1\. 概要

本ハンズオンでは、Docker Composeを使用して以下の3つのコンテナを立ち上げ、OAuth 2.0 / OIDC によるAPI保護のフローを体験します。

1.  **PostgreSQL**: Keycloakのデータを永続化するデータベース。
2.  **Keycloak**: 認証認可サーバー (IdP)。
3.  **API Server**: Python (Flask) で作成した簡易Webサーバー。Keycloakにトークンの検証 (Introspection) を依頼し、アクセス制御を行います。

## 2\. ディレクトリ構成

作業用のフォルダ（例: `keycloak-handson`）を作成し、以下の構成でファイルを作成します。

```text
keycloak-handson/
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── server.py
└── docker-compose.yml
```

-----

## 3\. ファイルの作成

### 3-1. APIサーバー用ファイルの作成 (`api/` フォルダ内)

まず `api` ディレクトリを作成し、その中に3つのファイルを作成します。

**① `api/requirements.txt`**
Pythonのライブラリ定義ファイルです。

```text
flask
requests
```

**② `api/Dockerfile`**
APIサーバーのコンテナ定義です。

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# コンテナ外からアクセスできるようにポート5000を開放
EXPOSE 5000

CMD ["python", "server.py"]
```

**③ `api/server.py`**
APIサーバーのソースコードです。環境変数経由で設定を読み込むように実装されています。

```python
from flask import Flask, request, jsonify
import requests
import os
import sys

app = Flask(__name__)

# --- 設定 (環境変数から読み込み、デフォルトはDocker内部通信用) ---
# Docker内ではサービス名 "keycloak" でアクセスします
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
REALM_NAME = os.getenv("REALM_NAME", "demo-realm")
CLIENT_ID = os.getenv("CLIENT_ID", "demo-client")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")

if not CLIENT_SECRET:
    print("WARNING: CLIENT_SECRET is not set. Token introspection will fail.")

# イントロスペクションエンドポイント（トークン検証用URL）
INTROSPECT_URL = f"{KEYCLOAK_URL}/realms/{REALM_NAME}/protocol/openid-connect/token/introspect"

def verify_token_via_introspection(token):
    """Keycloakにトークンを送信して有効性を確認する"""
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'token': token
    }
    try:
        # Keycloakに問い合わせ
        response = requests.post(INTROSPECT_URL, data=payload)
        response.raise_for_status()
        token_info = response.json()
        
        # active: true なら有効
        return token_info.get('active', False), token_info
    except Exception as e:
        print(f"Token validation error: {e}", file=sys.stderr)
        return False, {}

@app.route('/api/public', methods=['GET'])
def public_endpoint():
    """誰でもアクセスできるエンドポイント"""
    return jsonify({"message": "Public content: Accessible by anyone.", "status": "public"})

@app.route('/api/private', methods=['GET'])
def private_endpoint():
    """アクセストークンがないと見られないエンドポイント"""
    
    # 1. Authorizationヘッダーの取得
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Authorization header missing"}), 401

    # 2. "Bearer <token>" 形式からトークン部分を抽出
    parts = auth_header.split()
    if parts[0].lower() != 'bearer' or len(parts) != 2:
        return jsonify({"error": "Invalid header format"}), 401
    
    token = parts[1]

    # 3. Keycloakでトークン検証
    is_valid, token_info = verify_token_via_introspection(token)

    if not is_valid:
        return jsonify({"error": "Invalid or expired token"}), 401

    # 4. 成功時のレスポンス
    user = token_info.get('preferred_username', 'unknown')
    return jsonify({
        "message": f"Hello, {user}! You are authorized.",
        "status": "protected",
        "user_id": token_info.get('sub')
    })

if __name__ == '__main__':
    # 外部公開用に 0.0.0.0 でリッスン
    app.run(host='0.0.0.0', port=5000)
```

### 3-2. コンテナ構成定義ファイルの作成

ルートディレクトリに `docker-compose.yml` を作成します。

**`docker-compose.yml`**
※ `api` サービスの `CLIENT_SECRET` は、後ほどKeycloakの設定後に書き換えて再起動します。

```yaml
version: '3.8'

services:
  # 1. データベース (Keycloak用)
  postgres:
    image: postgres:15
    container_name: keycloak_postgres
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: keycloak
      POSTGRES_USER: keycloak
      POSTGRES_PASSWORD: password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U keycloak"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - keycloak-net

  # 2. Keycloak (IdP)
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    container_name: keycloak
    command: start-dev
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      # DB設定
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: password
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - keycloak-net

  # 3. API Server (Resource Server)
  api:
    build: ./api
    container_name: python_api
    ports:
      - "5000:5000"
    environment:
      # コンテナ内からKeycloakへの通信URL
      KEYCLOAK_URL: "http://keycloak:8080"
      REALM_NAME: "demo-realm"
      CLIENT_ID: "demo-client"
      # 【重要】Keycloak設定後に書き換える箇所
      CLIENT_SECRET: "CHANGE_ME_AFTER_SETUP"
    depends_on:
      - keycloak
    networks:
      - keycloak-net

networks:
  keycloak-net:
    driver: bridge
```

-----

## 4\. 環境の起動とKeycloakの初期設定

### 4-1. コンテナの起動

ターミナルで `docker-compose.yml` のあるディレクトリに移動し、以下を実行します。

```bash
docker compose up -d --build
```

  * `--build`: APIサーバーのイメージをビルドするために必要です。

Keycloakが起動するまで少し待ちます（約30秒〜1分）。
管理コンソール `http://localhost:8080/admin/` にアクセスできれば起動完了です。

### 4-2. Keycloakの設定 (GUI操作)

ブラウザで `http://localhost:8080/admin/` にアクセスし、`admin` / `admin` でログインします。

1.  **レルムの作成**:
      * 左上のプルダウンから **[Create Realm]**。
      * Realm name: `demo-realm` -\> [Create]。
2.  **クライアントの作成**:
      * Clients -\> **[Create client]**。
      * Client ID: `demo-client` -\> [Next]。
      * **Capability config**:
          * Client authentication: **On** (必須)
          * Authentication flow: `Standard flow` (On), `Direct access grants` (Off), `Service accounts roles` (On)。
          * [Next]。
      * **Login settings**:
          * Valid redirect URIs: `http://localhost:9999` (ポート9999を指定)
          * Web origins: `*` (念のため)
          * [Save]。
3.  **ユーザーの作成**:
      * Users -\> **[Add user]**。
      * Username: `user1` -\> [Create]。
      * Credentials -\> [Set password] -\> `password` (Temporary: Off) -\> [Save]。
4.  **Client Secret の取得**:
      * Clients -\> `demo-client` -\> **Credentials** タブ。
      * **Client Secret** の値をコピーします。

-----

## 5\. APIサーバーへのシークレット設定と再起動

APIサーバーがKeycloakと会話できるように、取得したシークレットを設定ファイルに反映させます。

1.  エディタで `docker-compose.yml` を開きます。
2.  `api` サービスの `environment` セクションにある `CLIENT_SECRET` を書き換えます。

<!-- end list -->

```yaml
    environment:
      KEYCLOAK_URL: "http://keycloak:8080"
      REALM_NAME: "demo-realm"
      CLIENT_ID: "demo-client"
      # ↓ ここにコピーした値を貼り付け
      CLIENT_SECRET: "ここにコピーしたシークレットを貼り付け" 
```

3.  設定を反映させるため、コンテナを再作成します。

<!-- end list -->

```bash
docker compose up -d api
```

※ `api` コンテナだけが再起動されます。Keycloakはそのまま動いています。

-----

## 6\. ハンズオン実行

ここからはターミナルで `curl` コマンドを使って動作確認します。

### 変数の準備

```bash
export KEYCLOAK_URL="http://localhost:8080"
export REALM_NAME="demo-realm"
export CLIENT_ID="demo-client"
# docker-compose.ymlに貼ったものと同じ値を設定
export CLIENT_SECRET="ここにコピーしたシークレット"
```

### Step 1: 公開APIへのアクセス（認証不要）

まずは何も持たずにAPIサーバーにアクセスしてみます。

```bash
curl http://localhost:5000/api/public
```

  * **結果**: `{"message": "Public content...", "status": "public"}` が返ればOKです。

### Step 2: 保護APIへのアクセス（失敗確認）

トークン無しで保護されたAPIにアクセスします。

```bash
curl http://localhost:5000/api/private
```

  * **結果**: `{"error": "Authorization header missing"}` (401エラー) が返ります。

### Step 3: トークンの取得 (Authorization Code Flow)

**1. 認可コードの取得 (ブラウザ)**
以下のURLにブラウザでアクセスします。

```text
http://localhost:8080/realms/demo-realm/protocol/openid-connect/auth?client_id=demo-client&response_type=code&redirect_uri=http://localhost:9999&scope=openid
```

  * ログイン後、接続エラー画面になります。
  * アドレスバーの `code=...` の値をコピーします。

**2. アクセストークンへの交換 (ターミナル)**

```bash
export AUTH_CODE="ブラウザからコピーしたコード"

curl -X POST "$KEYCLOAK_URL/realms/$REALM_NAME/protocol/openid-connect/token" \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "grant_type=authorization_code" \
 -d "client_id=$CLIENT_ID" \
 -d "client_secret=$CLIENT_SECRET" \
 -d "redirect_uri=http://localhost:9999" \
 -d "code=$AUTH_CODE" | jq .
```

  * 返ってきたJSONの中の `access_token` をコピーします。

<!-- end list -->

```bash
export ACCESS_TOKEN="取得したアクセストークン"
```

### Step 4: 保護APIへのアクセス（成功確認）

取得したトークンを使って、再度APIにアクセスします。
APIサーバー（コンテナ）は、裏側でKeycloak（コンテナ）と通信し、トークンが正しいかを確認します。

```bash
curl -H "Authorization: Bearer $ACCESS_TOKEN" http://localhost:5000/api/private
```

  * **成功時の結果**:

<!-- end list -->

```json
{
  "message": "Hello, user1! You are authorized.",
  "status": "protected",
  "user_id": "..."
}
```

これで、すべてのコンポーネント（DB、IdP、API）がDockerコンテナ上で連携し、正しくAPI保護が機能していることが確認できました。

-----

## 7\. 環境の削除

ハンズオン終了後、環境を完全に削除するには以下を実行します。

```bash
# コンテナの停止と削除
docker compose down

# データも削除する場合
rm -rf ./data
```