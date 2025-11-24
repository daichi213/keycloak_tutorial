- [【Phase 3】 Refresh Token Flow (トークンの有効期限と更新)](#phase-3-refresh-token-flow-トークンの有効期限と更新)
  - [🎯 学習目標](#-学習目標)
  - [📚 PDF参照](#-pdf参照)
  - [🛠 1. Keycloakの設定変更 (トークン寿命を短くする)](#-1-keycloakの設定変更-トークン寿命を短くする)
  - [🛠 2. Direct access grantsの有効化](#-2-direct-access-grantsの有効化)
  - [🚀 3. 実践ステップ (有効期限切れと更新の体験)](#-3-実践ステップ-有効期限切れと更新の体験)
- [💡 技術解説: リフレッシュトークンの運用](#-技術解説-リフレッシュトークンの運用)
  - [1. Refresh Token Rotation (リフレッシュトークンのローテーション)](#1-refresh-token-rotation-リフレッシュトークンのローテーション)
  - [2. オフラインアクセス (Offline Access)](#2-オフラインアクセス-offline-access)

### 【Phase 3】 Refresh Token Flow (トークンの有効期限と更新)

#### 🎯 学習目標

OAuth 2.0 / OIDC において、アクセストークンはセキュリティ上の理由から「短命（Short-lived）」に設計されます。期限切れになった際、ユーザーに再ログインを強いることなく、**Refresh Token** を使って新しいアクセストークンを取得するフローを体験します。

  * **Access Token (短命):** リソースへのアクセス許可証。盗難リスクを抑えるため寿命を短くする。
  * **Refresh Token (長命):** 新しいアクセストークンを発行するための引換券。通常、認可サーバー（Keycloak）に提示して使用する。
  * **Industry Mapping:**
      * **AWS Cognito / Auth0:** SDKを使用すると自動的に裏側でリフレッシュ処理が行われますが、その実体は今回行うAPIコールと同じです。
      * **Security Best Practice:** 「アクセストークンは数分〜数時間、リフレッシュトークンは数日〜数ヶ月」という設定が一般的です。

#### 📚 PDF参照

  * **Chapter 12: Managing Tokens and Sessions**
      * [cite\_start]"Managing ID tokens’ and access tokens’ lifetimes"[cite: 1063, 1064]: トークン寿命の設定方法。
      * [cite\_start]"Managing refresh tokens’ lifetimes"[cite: 1067]: リフレッシュトークンの寿命について。

-----

#### 🛠 1. Keycloakの設定変更 (トークン寿命を短くする)

デフォルトのアクセストークン寿命（5分）だと、期限切れを待つのが大変です。テスト用に**1分**に変更します。

1.  Keycloak管理コンソール (`http://localhost:8080/admin`) にログイン。
2.  左メニュー **Realm Settings** \> **Tokens** タブを選択。
3.  **Access Token Lifespan** を `1` `Minute` に変更。
4.  画面一番下の **Save** をクリック。

#### 🛠 2. Direct access grantsの有効化

1.  Keycloak管理コンソール (`http://localhost:8080/admin`) にログイン。
2.  左メニュー **Clients** \> **Settings** タブを選択。
3.  **Direct access grants** を Check に変更。

-----

#### 🚀 3. 実践ステップ (有効期限切れと更新の体験)

これまでは `client_credentials` グラントを使っていましたが、標準仕様ではこのフローでRefresh Tokenは発行されません。
今回は、ユーザー `user1` を使用した **Resource Owner Password Credentials Grant** (`grant_type=password`) を使用して、Refresh Tokenを取得します。

> **Note:** Password Grantは現在非推奨傾向にありますが、`curl` だけで手軽にRefresh Tokenフローを検証するには最適です。

**Step 1: トークンセットの取得 (Access Token + Refresh Token)**

```bash
# ユーザー user1 でログインし、レスポンス全体をJSONファイルに保存
curl -s -X POST 'http://localhost:8080/realms/demo-realm/protocol/openid-connect/token' \
  -H 'Host: keycloak:8080' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=demo-client' \
  -d 'client_secret=bABIT6UsHLd1TjwXzsx5YXmbEoaboZl1' \
  -d 'username=user1' \
  -d 'password=password' \
  -d 'grant_type=password' > tokens.json

# アクセストークンとリフレッシュトークンを変数に抽出
export ACCESS_TOKEN=$(cat tokens.json | jq -r .access_token)
export REFRESH_TOKEN=$(cat tokens.json | jq -r .refresh_token)

# 確認
echo "AT: ${ACCESS_TOKEN:0:20}..."
echo "RT: ${REFRESH_TOKEN:0:20}..."
```

※ `client_secret` はご自身の環境の値に合わせてください。

**Step 2: APIアクセス (成功確認)**

取得直後なのでアクセスできるはずです。

```bash
curl http://localhost:5000/secure -H "Authorization: Bearer $ACCESS_TOKEN"
```

  * **結果:** `Access Granted...` (user: user1)

**Step 3: タイムトラベル (1分待機)**

設定した寿命（1分）が過ぎるのを待ちます。コーヒーを一口飲むか、以下のコマンドで待ちましょう。

```bash
sleep 65
```

**Step 4: APIアクセス (期限切れ確認)**

同じアクセストークンで再度アクセスします。

```bash
curl http://localhost:5000/secure -H "Authorization: Bearer $ACCESS_TOKEN"
```

  * **期待される結果:**
      * APIレスポンス: `{"error": "Token is invalid or expired"}`
      * Dockerログ (`docker-compose logs api`): `Validation Error: Token has expired` (PyJWTの `ExpiredSignatureError`)

**Step 5: トークンのリフレッシュ (Refresh Token Flow)**

ここがハイライトです。期限切れのアクセストークンを捨て、持っていた **Refresh Token** をKeycloakに提示して、新しいアクセストークンをもらいます。

```bash
# リフレッシュリクエスト
# grant_type=refresh_token を指定します
curl -s -X POST 'http://localhost:8080/realms/demo-realm/protocol/openid-connect/token' \
  -H 'Host: keycloak:8080' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=demo-client' \
  -d 'client_secret=bABIT6UsHLd1TjwXzsx5YXmbEoaboZl1' \
  -d 'grant_type=refresh_token' \
  -d "refresh_token=$REFRESH_TOKEN" > new_tokens.json

# 新しいアクセストークンを抽出
export NEW_ACCESS_TOKEN=$(cat new_tokens.json | jq -r .access_token)

echo "New AT: ${NEW_ACCESS_TOKEN:0:20}..."
```

> **Note:** 通常、レスポンスには「新しいアクセストークン」と共に「新しいリフレッシュトークン」も含まれます。セキュリティ設定（Refresh Token Rotation）によっては、古いリフレッシュトークンはこの時点で無効化されます。

**Step 6: 新しいトークンでAPIアクセス (復活)**

```bash
curl http://localhost:5000/secure -H "Authorization: Bearer $NEW_ACCESS_TOKEN"
```

  * **結果:** `Access Granted...`

-----

### 💡 技術解説: リフレッシュトークンの運用

#### 1\. Refresh Token Rotation (リフレッシュトークンのローテーション)

  * Keycloakの設定で `Revoke Refresh Token` (管理画面 Realm Settings \> Tokens) をONにすると、リフレッシュトークンを使うたびに新しいリフレッシュトークンが発行され、**古いものは即座に無効化**されます。
  * これは、万が一リフレッシュトークンが漏洩した際の影響を最小限に抑えるための重要なセキュリティ対策です。

#### 2\. オフラインアクセス (Offline Access)

  * 通常のRefresh Tokenは「SSOセッション」に紐付いており、ユーザーがブラウザでログアウトしたり、セッションアイドル時間が過ぎると無効になります。
  * モバイルアプリなどで「永続的にログイン状態を保ちたい」場合は、特別なスコープ `offline_access` を要求して **Offline Token** を取得します。これはDBに永続化され、セッションが切れても（明示的にRevokeされるまで）有効です。
