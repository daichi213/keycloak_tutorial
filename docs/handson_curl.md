- [Keycloak OAuth 2.0 \& OIDC ハンズオン (完全版)](#keycloak-oauth-20--oidc-ハンズオン-完全版)
  - [🛠 0. 環境準備 (Environment Setup)](#-0-環境準備-environment-setup)
    - [設定が毎回失われる構成](#設定が毎回失われる構成)
    - [📂 ファイル構成](#-ファイル構成)
    - [📄 docker-compose.yml](#-docker-composeyml)
    - [🚀 起動と停止](#-起動と停止)
  - [⚙️ 1. Keycloak設定 (Configuration)](#️-1-keycloak設定-configuration)
    - [1-1. レルム (Realm) の作成](#1-1-レルム-realm-の作成)
    - [1-2. クライアント (Client) の作成と詳細設定](#1-2-クライアント-client-の作成と詳細設定)
    - [1-3. シークレットの取得](#1-3-シークレットの取得)
    - [1-4. ユーザー (User) の作成](#1-4-ユーザー-user-の作成)
  - [🚀 Part 1: Client Credentials Flow (サーバー間通信)](#-part-1-client-credentials-flow-サーバー間通信)
    - [変数の設定](#変数の設定)
    - [Step 1. トークン取得リクエスト](#step-1-トークン取得リクエスト)
    - [解説](#解説)
  - [🚀 Part 2: Authorization Code Flow \& OIDC (Webアプリ認証)](#-part-2-authorization-code-flow--oidc-webアプリ認証)
    - [Step 2. 認可コードフロー (Authorization Code Flow)](#step-2-認可コードフロー-authorization-code-flow)
      - [手順 A: 認可リクエスト (ブラウザ操作)](#手順-a-認可リクエスト-ブラウザ操作)
      - [手順 B: トークン交換リクエスト](#手順-b-トークン交換リクエスト)
    - [Step 3. OIDC UserInfo \& トークン検証](#step-3-oidc-userinfo--トークン検証)
      - [手順 C: UserInfo エンドポイント (OIDC)](#手順-c-userinfo-エンドポイント-oidc)
      - [手順 D: JWTトークンの中身の理解](#手順-d-jwtトークンの中身の理解)
  - [🛡️ PKCE (ピクシー) ハンズオン](#️-pkce-ピクシー-ハンズオン)
    - [Step 1: PKCE用クライアントの作成 (Public Client)](#step-1-pkce用クライアントの作成-public-client)
    - [Step 2: Verifier と Challenge の生成](#step-2-verifier-と-challenge-の生成)
    - [Step 3: 認可リクエスト (Challengeを送信)](#step-3-認可リクエスト-challengeを送信)
      - [URLの作成](#urlの作成)
      - [実行手順](#実行手順)
    - [Step 4: トークン交換 (Verifierを送信)](#step-4-トークン交換-verifierを送信)
    - [✅ 成功の確認](#-成功の確認)
    - [まとめ](#まとめ)
  - [🧹 後片付け](#-後片付け)

# Keycloak OAuth 2.0 & OIDC ハンズオン (完全版)

このハンズオンでは、DockerでKeycloakを起動し、`curl` コマンドを使って以下の2つの主要なフローをステップバイステップで検証します。

1.  **Client Credentials Flow**: サーバー間通信（システム間連携）
2.  **Authorization Code Flow + OIDC**: Webアプリ認証（ユーザーログイン）

## 🛠 0. 環境準備 (Environment Setup)

### 設定が毎回失われる構成

まず、Keycloakをコンテナで起動します。

```bash
docker run -p 8080:8080 --name keycloak \
  -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:latest \
  start-dev
```

  * **管理コンソール**: `http://localhost:8080/admin/`
  * **管理者アカウント**: `admin` / `admin`

### 📂 ファイル構成

任意のディレクトリ（例: `keycloak-hands-on`）を作成し、その中に以下のファイルを配置してください。

```text
.
├── docker-compose.yml
└── data/               # 自動生成されます（ここにデータが永続化される）
```

### 📄 docker-compose.yml

```yaml
version: '3.8'

services:
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

  keycloak:
    image: quay.io/keycloak/keycloak:latest
    container_name: keycloak
    command: start-dev
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      # データベース接続設定
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: password
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
```

### 🚀 起動と停止

**起動:**

```bash
wsl -u root
docker compose up -d
```

※ 初回起動時はデータベースの初期化が入るため、管理コンソール（`http://localhost:8080/admin`）にアクセスできるまで数十秒かかる場合があります。

**停止:**

```bash
docker compose stop
```

**データの削除（完全に初期化したい場合）:**

```bash
docker compose down
rm -rf ./data
```

-----

## ⚙️ 1. Keycloak設定 (Configuration)

認証を行うための箱（レルム）、アプリ（クライアント）、ユーザーを作成します。

### 1-1. レルム (Realm) の作成

Keycloakにおける「テナント」や「領域」の単位です。

1.  管理コンソールにログイン。
2.  左上の「Keycloak」プルダウンから **[Create Realm]** をクリック。
3.  **Realm name**: `demo-realm`
4.  [Create] をクリック。

### 1-2. クライアント (Client) の作成と詳細設定

OAuthにおける「アプリケーション」の定義です。

1.  左メニュー **Clients** -\> **[Create client]** をクリック。
2.  **General settings**:
      * **Client type**: `OpenID Connect`
      * **Client ID**: `demo-client` **(※ここが必須項目です)**
      * [Next] をクリック。
3.  **Capability config** (重要):
      * **Client authentication**: `On`
          * *説明: クライアントシークレットを使用して、アプリ自体を認証します。*
      * **Authorization**: `Off`
          * *説明: 今回は細かいリソース認可（UMA）は扱いません。*
      * **Authentication flow**:
          * `Standard flow`: **Check** (Step 2で使用。Authorization Code Flowのこと)
          * `Direct access grants`: **Uncheck** (ユーザー名/PWを直接アプリに渡すレガシーな方式なので無効化推奨)
          * `Service accounts roles`: **Check** (Step 1で使用。Client Credentials Flowのこと)
      * [Next] をクリック。
4.  **Login settings**:
      * **Valid redirect URIs**: `http://localhost:9999`
          * *説明: 認可完了後に戻る許可されたURLです。今回はブラウザの先読み防止のため、あえて接続できないポート9999を指定します。*
      * [Save] をクリック。

### 1-3. シークレットの取得

設定完了画面、または **Clients** -\> `demo-client` -\> **Credentials** タブから、**Client Secret** をコピーして控えてください。

### 1-4. ユーザー (User) の作成

Step 2でログインする一般ユーザーです。

1.  左メニュー **Users** -\> **[Add user]**。
2.  **Username**: `user1` -\> [Create]。
3.  **Credentials** タブ -\> [Set password]。
4.  **Password**: `password` / **Temporary**: `Off` -\> [Save]。

-----

## 🚀 Part 1: Client Credentials Flow (サーバー間通信)

このパートは **OAuth 2.0** のフローです。ユーザー（人間）は介在しません。バッチ処理やバックエンドシステム同士がAPIを叩く際に使用します。

### 変数の設定

ターミナルで以下を実行してください。

```bash
export KEYCLOAK_URL="http://localhost:8080"
export REALM_NAME="demo-realm"
export CLIENT_ID="demo-client"
export CLIENT_SECRET="<取得したClient Secret>" # ←書き換える
```

### Step 1. トークン取得リクエスト

```bash
curl -X POST "$KEYCLOAK_URL/realms/$REALM_NAME/protocol/openid-connect/token" \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "grant_type=client_credentials" \
 -d "client_id=$CLIENT_ID" \
 -d "client_secret=$CLIENT_SECRET" | jq .
```

### 解説

  * **`grant_type=client_credentials`**: 「私（クライアント）自身の権限でトークンをください」という指定です。
  * 返却されるアクセストークンには、ユーザーID (`sub`) ではなく、クライアントのサービスアカウントIDが含まれます。

-----

## 🚀 Part 2: Authorization Code Flow & OIDC (Webアプリ認証)

このパートは **OAuth 2.0 + OpenID Connect** のフローです。ユーザーがブラウザを介してログインし、アプリに権限を与えます。

### Step 2. 認可コードフロー (Authorization Code Flow)

#### 手順 A: 認可リクエスト (ブラウザ操作)

以下のURLをブラウザのアドレスバーに入力してください。

```text
http://localhost:8080/realms/demo-realm/protocol/openid-connect/auth?client_id=demo-client&response_type=code&redirect_uri=http://localhost:9999&scope=openid
```

1.  Keycloakの画面で `user1` / `password` でログインします。
2.  ログイン後、ブラウザは `localhost:9999` にリダイレクトしようとして「接続できません」等のエラーになります。
3.  **これで成功です。** ブラウザのアドレスバーを見てください。
    `http://localhost:9999/?session_state=...&code=...`
4.  `code=` の後ろの文字列（`&`の手前まで）をコピーしてください。これが **認可コード** です。

#### 手順 B: トークン交換リクエスト

取得したコードをアクセストークンに交換します。
**※重要:** `redirect_uri` は手順Aで指定したものと**完全に一致**している必要があります。

```bash
# コピーしたコードをセット
export AUTH_CODE="<ブラウザからコピーしたcode>"

# トークン交換
curl -X POST "$KEYCLOAK_URL/realms/$REALM_NAME/protocol/openid-connect/token" \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "grant_type=authorization_code" \
 -d "client_id=$CLIENT_ID" \
 -d "client_secret=$CLIENT_SECRET" \
 -d "redirect_uri=http://localhost:9999" \
 -d "code=$AUTH_CODE" | jq .
```

成功すると `access_token` (JWT) が返却されます。このトークンを環境変数に入れます。

```bash
export ACCESS_TOKEN="<レスポンスのaccess_tokenの値>"
```

### Step 3. OIDC UserInfo & トークン検証

#### 手順 C: UserInfo エンドポイント (OIDC)

アクセストークンを使ってユーザーのプロフィール情報を取得します。これはOAuth 2.0の拡張である **OpenID Connect** の機能です。

```bash
curl -X GET "$KEYCLOAK_URL/realms/$REALM_NAME/protocol/openid-connect/userinfo" \
 -H "Authorization: Bearer $ACCESS_TOKEN" | jq .
```

#### 手順 D: JWTトークンの中身の理解

取得したアクセストークン（またはUserInfoの結果）がどのような意味を持つか、ご提示いただいたJSON例を元に解説します。

```bash
# アクセストークンのPayload部分（2番目のパーツ）をデコード
echo $ACCESS_TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq .
```

**▼ アクセストークン(JWT)のデコード例と解説**

```json
{
  "exp": 1763787499,                                // 【Expiration Time】 トークンの有効期限 (Unix Time)
  "iat": 1763787199,                                // 【Issued At】 発行日時
  "jti": "onrtac:f4b5b2fd...",                      // 【JWT ID】 トークンの一意な識別子
  "iss": "http://localhost:8080/realms/demo-realm", // 【Issuer】 発行者 (KeycloakのURL)
  "sub": "6bc1fa24-2f06-...",                       // 【Subject】 ユーザーの一意なID (不変の識別子)
  "typ": "Bearer",                                  // トークンのタイプ
  "azp": "demo-client",                             // 【Authorized Party】 トークンを要求したクライアントID
  "session_state": "bf573081...",                   // Keycloak内部のセッションID
  "scope": "openid email profile",                  // 【Scope】 許可された権限範囲
  "email_verified": false,
  "preferred_username": "user1",                    // ログインに使用したユーザー名
  "email": "user1@test.com"
}
```

**重要な項目の解説:**

  * **`sub` (Subject)**: アプリケーションがユーザーを識別するために使うべき**最も重要なID**です。`preferred_username` は変更可能ですが、`sub` は不変です。
  * **`azp` (Authorized Party)**: このトークンが「どのアプリのために発行されたか」を示します。バックエンドAPI側で「特定のアプリからのアクセスのみ許可したい」場合にチェックします。
  * **`iss` (Issuer)**: 信頼できる発行元からのトークンかを確認するために使用します。
  * **`exp` (Expiration)**: APIサーバーはこの時間を過ぎたトークンを拒否しなければなりません。

-----

## 🛡️ PKCE (ピクシー) ハンズオン

**PKCEとは？**
従来のAuthorization Code Flowのセキュリティ強化版です。
スマホアプリやSPA（シングルページアプリケーション）のように、**「Client Secret（秘密鍵）を安全に保存できない」** 環境（Public Client）で使用します。
Client Secretを送る代わりに、その場で生成した「暗号鍵のペア」を使って身元を証明します。


-----

### Step 1: PKCE用クライアントの作成 (Public Client)

PKCEを使用する場合、クライアントの設定が前回（Confidential Client）とは異なります。

1.  Keycloak管理コンソール (`http://localhost:8080/admin/`) にログイン。
2.  **Clients** -\> **[Create client]** をクリック。
3.  **General settings**:
      * Client ID: `pkce-client`
      * [Next] をクリック。
4.  **Capability config (※ここが重要)**:
      * **Client authentication**: `Off`
          * *これ重要！シークレットを持たない「Public Client」にします。*
      * **Authentication flow**:
          * `Standard flow`: **Check**
          * `Direct access grants`: **Uncheck**
          * `Service accounts roles`: **Uncheck** (Public Clientでは使えません)
      * [Next] をクリック。
5.  **Login settings**:
      * **Valid redirect URIs**: `http://localhost:9999`
          * *※今回もブラウザの先読み防止のためポート9999を使います。*
      * **Web origins**: `*` (CORSエラー防止のため念のため)
      * [Save] をクリック。

-----

### Step 2: Verifier と Challenge の生成

PKCEでは、クライアント側（あなた）が「合言葉」を生成する必要があります。
本来はアプリが自動生成しますが、ハンズオンでは手動で計算します。

1.  **Code Verifier (コードヴェリファイア)**: ランダムな文字列。
2.  **Code Challenge (コードチャレンジ)**: Verifierをハッシュ化(SHA256)してBase64URLエンコードしたもの。

計算が面倒なので、以下の **「計算済みの値」** をそのまま変数にセットして使ってください。

```bash
# 環境変数のセット（ターミナルで実行）
export KEYCLOAK_URL="http://localhost:8080"
export REALM_NAME="demo-realm"
export CLIENT_ID="pkce-client"

# --- PKCE用の合言葉（計算済み） ---
# Code Verifier (秘密のランダム文字列)
export CODE_VERIFIER="IpK0y1g2Z3x4C5v6B7n8M9l0K1j2H3g4F5d6S7a8P9o"

# Code Challenge (Verifierをハッシュ化したもの)
# 計算式: Base64URL(SHA256(CODE_VERIFIER))
export CODE_CHALLENGE="Z2ZkYmE2NmE1...（下記の値を使ってください）" 
# ※正確な値を入れるため、手動計算を避けて以下のコマンドでセットしてください
export CODE_CHALLENGE="os-Ofp3y1g2Z3x4C5v6B7n8M9l0K1j2H3g4F5d6S7a8"

# ※上記はあくまで例です。今回はハンズオンを簡単にするため、
#  以下の「動作確認済みペア」をコピーして貼り付けてください。
```

**▼ 以下のコマンドブロックをコピーしてターミナルで実行してください**

```bash
export KEYCLOAK_URL="http://localhost:8080"
export REALM_NAME="demo-realm"
export CLIENT_ID="pkce-client"

# このVerifier(元の値)とChallenge(変換後の値)はペアです
export CODE_VERIFIER="a-very-long-random-string-created-by-client-side-for-pkce-security-check"
export CODE_CHALLENGE="s3L5B2X4F5d6S7a8P9o0I1u2Y3t4R5e6W7q8Q9w0E1r"

# 実際には上記のChallenge値はデタラメですが、
# Keycloak側でハッシュ計算が一致しないとエラーになるため、
# 正しいハッシュ計算を行う「Pythonワンライナー」を用意しました。
# ↓ これを実行して正しい CHALLENGE を生成・セットしてください。

export CODE_CHALLENGE=$(python3 -c "import hashlib, base64, os; v = os.environ['CODE_VERIFIER']; d = hashlib.sha256(v.encode('utf-8')).digest(); print(base64.urlsafe_b64encode(d).decode().rstrip('='))")

# 正しく生成されたか確認
echo "Verifier:  $CODE_VERIFIER"
echo "Challenge: $CODE_CHALLENGE"
```

-----

### Step 3: 認可リクエスト (Challengeを送信)

ブラウザでログインします。
前回のURLに加えて、`code_challenge` と `code_challenge_method` を送るのがポイントです。

#### URLの作成

ターミナルでURLを表示させます。

```bash
echo "${KEYCLOAK_URL}/realms/${REALM_NAME}/protocol/openid-connect/auth?client_id=${CLIENT_ID}&response_type=code&redirect_uri=http://localhost:9999&scope=openid&code_challenge=${CODE_CHALLENGE}&code_challenge_method=S256"
```

#### 実行手順

1.  出力されたURLをコピーしてブラウザに貼り付けます。
2.  ログイン画面が出たら `user1` / `password` でログインします。
3.  画面が「接続できません」になります（ポート9999のため）。
4.  アドレスバーから `code=...` の部分をコピーします。

-----

### Step 4: トークン交換 (Verifierを送信)

ここがPKCEのハイライトです。
`client_secret` を送る代わりに、**`code_verifier`（Challengeの元ネタ）** を送ります。
Keycloakは「受け取ったVerifierをハッシュ化して、さっきブラウザから送られてきたChallengeと一致するか？」を確認します。

```bash
# Step 3で取得したコードをセット
export AUTH_CODE="ブラウザからコピーしたコード"

# トークンリクエスト
curl -X POST "$KEYCLOAK_URL/realms/$REALM_NAME/protocol/openid-connect/token" \
 -H "Content-Type: application/x-www-form-urlencoded" \
 -d "grant_type=authorization_code" \
 -d "client_id=$CLIENT_ID" \
 -d "code_verifier=$CODE_VERIFIER" \
 -d "redirect_uri=http://localhost:9999" \
 -d "code=$AUTH_CODE" | jq .
```

**注目ポイント:**

  * `client_secret` の行が**ありません**。
  * 代わりに `code_verifier` を送っています。

### ✅ 成功の確認

JSONが返ってくれば成功です！

もし `error="invalid_grant"` や `PKCE verification failed` が出る場合は、`CODE_VERIFIER` と `CODE_CHALLENGE` のペアが数学的に合っていない（Step 2の生成ミス）可能性があります。

### まとめ

このPKCEフローによって、万が一途中で「認可コード」を盗まれても、攻撃者は「Code Verifier（元の文字列）」を知らないため、アクセストークンへの交換ができません。これがモバイルアプリ等でPKCEが必須とされる理由です。

## 🧹 後片付け

```bash
docker stop keycloak
docker rm keycloak
```

以上でハンズオンは完了です。
Client Credentials（システム認証）と Authorization Code（ユーザー認証）の違い、および `redirect_uri` の厳密性について体感いただけたかと思います。