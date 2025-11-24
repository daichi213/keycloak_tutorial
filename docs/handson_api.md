- [【Phase 1 改訂版】 イントロスペクション方式によるAPI保護](#phase-1-改訂版-イントロスペクション方式によるapi保護)
  - [🎯 学習目標 (Revised)](#-学習目標-revised)
  - [🛠 1. 環境設定の修正 (`docker-compose.yml`)](#-1-環境設定の修正-docker-composeyml)
  - [🛠 2. APIサーバーの実装 (`api/server.py`)](#-2-apiサーバーの実装-apiserverpy)
  - [🚀 3. 実践ステップ (検証フロー)](#-3-実践ステップ-検証フロー)
- [💡 今回の学びポイント: Client Credentials Flow と Issuer の整合性](#-今回の学びポイント-client-credentials-flow-と-issuer-の整合性)
  - [1. どこでエラーが起きていたか？ (再確認)](#1-どこでエラーが起きていたか-再確認)
  - [2. なぜ今回の修正が "Prod-Ready" なのか？](#2-なぜ今回の修正が-prod-ready-なのか)
  - [3. 他社サービスとの比較 (Industry Mapping)](#3-他社サービスとの比較-industry-mapping)


# 【Phase 1 改訂版】 イントロスペクション方式によるAPI保護

## 🎯 学習目標 (Revised)

  * **OAuth 2.0 Token Introspection (RFC 7662)**: APIサーバーが「不透明なトークン」を認可サーバーに問い合わせて検証する。
  * **Issuerの一貫性**: トークンの発行者（`iss`）と、検証時の認可サーバーの認識を一致させる重要性を学ぶ。
  * **Production-Ready Code**: APIサーバーのコードに環境依存のハックを含めず、構成（Configuration）とリクエストヘッダーで環境差異を吸収する。

## 🛠 1. 環境設定の修正 (`docker-compose.yml`)

前回、トラブルシュートのために追加した `KC_HOSTNAME_URL` 設定は、今回の「Hostヘッダーで制御する」方針では邪魔になります（これがあると、Hostヘッダーを無視してURLを固定してしまうため）。

**設定を「動的な解決（Strictモード無効）」の状態に戻します。**

`docker-compose.yml` の `keycloak` サービス部分を以下のように修正してください（`KC_HOSTNAME_URL` を削除します）。

```yaml
  # 2. Keycloak (IdP)
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    container_name: keycloak
    command: start-dev
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: password
      # ▼▼▼ 修正箇所: 固定URL設定を削除し、Strictモードのみ無効化 ▼▼▼
      KC_HOSTNAME_STRICT: "false"
      KC_HOSTNAME_STRICT_BACKCHANNEL: "false"
      # KC_HOSTNAME_URL: ... (削除)
      # ▲▲▲ 修正箇所 ▲▲▲
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - keycloak-net
```

## 🛠 2. APIサーバーの実装 (`api/server.py`)

APIサーバーのコードから、前回追加した `headers={'Host': 'localhost:8080'}` というハックを削除し、標準的な実装に戻します。

```python
from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Docker内部通信用URL
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080")
REALM_NAME = os.environ.get("REALM_NAME", "demo-realm")
CLIENT_ID = "demo-client"
# 環境変数からSecretを取得（なければ空文字）
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "") 

INTROSPECT_URL = f"{KEYCLOAK_URL}/realms/{REALM_NAME}/protocol/openid-connect/token/introspect"

def introspect_token(access_token):
    """
    RFC 7662 に基づく標準的なイントロスペクションリクエスト
    """
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'token': access_token,
    }
    
    try:
        # ★修正: 特殊なヘッダー操作を削除。純粋なPOSTリクエストに戻す。
        response = requests.post(INTROSPECT_URL, data=payload, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Introspection Error: {e}")
        return {'active': False}

@app.route('/secure')
def secure():
    auth_header = request.headers.get('Authorization', None)
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401

    parts = auth_header.split()
    if parts[0].lower() != 'bearer' or len(parts) != 2:
        return jsonify({"error": "Invalid Header Format"}), 401

    access_token = parts[1]

    # イントロスペクション実行
    token_info = introspect_token(access_token)

    # active: true かどうかをチェック
    if not token_info.get('active'):
        return jsonify({"error": "Token is invalid or expired"}), 401

    return jsonify({
        "message": "Access Granted via Introspection!",
        "user": token_info.get('preferred_username'),
        "scope": token_info.get('scope'),
        "client_id": token_info.get('client_id'),
        "iss": token_info.get('iss') # 確認用にIssuerを表示
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

**反映:**

```bash
docker-compose up -d --build
```

-----

## 🚀 3. 実践ステップ (検証フロー)

ここがポイントです。
トークンを取得する際、ホストマシン (`curl`) からは `localhost` に接続しますが、**「私は `keycloak:8080` にアクセスしています」** と宣言します。

**Step 1: アクセストークンの取得 (Hostヘッダー指定)**

```bash
# トークンを取得
# -H "Host: keycloak:8080" を追加することで、発行されるトークンの iss を "http://keycloak:8080..." にする
export TOKEN=$(curl -s -X POST 'http://localhost:8080/realms/demo-realm/protocol/openid-connect/token' \
  -H 'Host: keycloak:8080' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=demo-client' \
  -d 'client_secret=bABIT6UsHLd1TjwXzsx5YXmbEoaboZl1' \
  -d 'grant_type=client_credentials' | jq -r .access_token)

# トークンが取れたか確認
echo $TOKEN
```

> ※ `client_secret` はご自身の環境の値に合わせてください。

**Step 2: APIサーバーへアクセス**

```bash
curl http://localhost:5000/secure \
  -H "Authorization: Bearer $TOKEN"
```

**成功時のレスポンス例:**

```json
{
  "client_id": "demo-client",
  "iss": "http://keycloak:8080/realms/demo-realm", 
  "message": "Access Granted via Introspection!",
  "scope": "email profile",
  "user": "service-account-demo-client"
}
```

`iss` が `http://keycloak:8080...` となっており、APIサーバー内部から見たKeycloakのURLと一致しているため、検証が成功します。

-----

# 💡 今回の学びポイント: Client Credentials Flow と Issuer の整合性

今回のエラーとその解決策は、**「認証基盤における "名前（Identity）" の管理」** という本質的なテーマを含んでいます。

## 1\. どこでエラーが起きていたか？ (再確認)

  * **Client Credentials Flow**: マシン間通信（M2M）で使われるフローです。
  * **Keycloakの検証ロジック**:
      * イントロスペクションのエンドポイント (`POST /token/introspect`) は、受け取ったトークンを発行したのが「自分自身かどうか」を確認します。
      * この際、「現在の自分へのリクエストURL（Hostヘッダー）」と「トークン内の `iss` クレーム」を比較します。

## 2\. なぜ今回の修正が "Prod-Ready" なのか？

前回の修正案（APIコード内でヘッダーを書き換える）は、アプリケーションコードに「インフラ構成の事情（Dockerのネットワーク名）」が漏れ出していました。これは密結合であり、環境が変わる（例: Kubernetesに移行する）と動かなくなります。

**今回の修正（クライアント側でHostヘッダーを指定）が優れている理由:**

  * **Resource Server (API) の責務分離**: APIサーバーは「来たトークンを検証先に投げる」という標準的な動作のみを行っており、環境依存がありません。
  * **リバースプロキシのシミュレーション**: 本番環境では、Load Balancerやリバースプロキシが `Host` ヘッダーを制御します（例: ユーザーは `api.example.com` にアクセスするが、バックエンドのKeycloakには `Host: auth.example.com` としてルーティングするなど）。
  * 今回の `curl -H "Host: keycloak:8080"` は、本番環境における「正しく構成されたクライアント、またはGateway」の挙動をシミュレートしています。

## 3\. 他社サービスとの比較 (Industry Mapping)

| 概念 | Keycloak (Self-hosted) | AWS Cognito | Okta / Auth0 |
| :--- | :--- | :--- | :--- |
| **Issuer (iss)** | 設定 (`KC_HOSTNAME`) やリクエストヘッダー (`Host`) で変動しうる。**設計が必要。** | `https://cognito-idp.{region}.amazonaws.com/{pool_id}` で固定。変動しない。 | `https://{your-org}.okta.com` で固定。カスタムドメインも設定可。 |
| **Introspection** | 標準サポート (RFC 7662)。セッション破棄を即時検知できる。 | 非対応 (標準機能としては提供なし)。トークンの有効期限切れを待つか、独自実装が必要。 | 標準サポート。 |
| **Client Credentials** | Service Account機能として実装。 | User PoolのApp Client設定で有効化。 | M2M Applicationとして実装。 |

**結論:**
マネージドサービス（Cognito/Okta）は `iss` が固定されているため、このようなトラブルは起きにくいです。
しかし、Keycloakのようなセルフホスト型IAMでは、**「誰が（どのホスト名が）正当なIssuerなのか」** をインフラ設計段階で決めておく必要があります。今回のハンズオンは、その「Issuer設計の重要性」を学ぶ良い機会となりました。
