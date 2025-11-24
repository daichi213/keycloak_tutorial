from flask import Flask, request, jsonify
import requests
import jwt
from jwt import PyJWKClient
import os
import logging
import sys

# --- 1. ロギング設定 ---
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- 2. 設定値のロード ---
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080")
REALM_NAME = os.environ.get("REALM_NAME", "demo-realm")
CLIENT_ID = "demo-client"
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")

# 検証モードの切り替え ('offline' or 'introspect')
VALIDATION_MODE = os.environ.get("VALIDATION_MODE", "offline")

# 期待するIssuerとAudience
# Note: トークン取得時に 'Host: keycloak:8080' を指定した場合、Issuerは以下のようになります
EXPECTED_ISSUER = f"http://keycloak:8080/realms/{REALM_NAME}"
EXPECTED_AUDIENCE = "account"

# エンドポイントURLの構築
INTROSPECT_URL = f"{KEYCLOAK_URL}/realms/{REALM_NAME}/protocol/openid-connect/token/introspect"
JWKS_URL = f"{KEYCLOAK_URL}/realms/{REALM_NAME}/protocol/openid-connect/certs"

# JWKSクライアントの初期化 (Offline検証用)
jwks_client = PyJWKClient(JWKS_URL)


def introspect_token(access_token: str) -> dict:
    """
    Keycloakのイントロスペクションエンドポイントを使用してトークンを検証します (RFC 7662)。

    この方式は、トークンが署名的に正しくても、サーバー側で無効化(Revoke)されている場合に
    即座に検知できる利点があります。ただし、リクエスト毎にHTTP通信が発生します。

    Args:
        access_token (str): 検証対象のアクセストークン (Bearer token string)。

    Returns:
        dict: トークンが有効な場合はそのメタデータを含む辞書。
              無効、または通信エラーの場合はNoneを返します。
    """
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'token': access_token,
    }
    
    try:
        # Keycloakへ問い合わせ
        response = requests.post(INTROSPECT_URL, data=payload, timeout=5)
        response.raise_for_status()
        token_info = response.json()
        
        # 'active' プロパティが true でなければ無効とみなす
        if not token_info.get('active'):
            logger.warning("Introspection result: Token is not active.")
            return None
            
        logger.info("Introspection successful.")
        return token_info

    except requests.exceptions.RequestException as e:
        logger.error(f"Introspection HTTP Error: {e}")
        return None


def verify_token_offline(access_token: str) -> dict:
    """
    公開鍵(JWKS)を使用して、ローカルでトークンの署名とクレームを検証します (Stateless)。

    Keycloakへの通信は公開鍵取得時(キャッシュなしの場合)のみ発生するため、
    パフォーマンスに優れています。

    Args:
        access_token (str): 検証対象のアクセストークン (Bearer token string)。

    Returns:
        dict: 検証に成功し、デコードされたトークンのペイロード(Claims)。
              署名不一致や期限切れなどの場合はNoneを返します。
    """
    try:
        # 1. トークンヘッダーのkid(鍵ID)に一致する公開鍵を取得
        signing_key = jwks_client.get_signing_key_from_jwt(access_token)

        # 2. 署名検証とデコード (PyJWT)
        data = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=EXPECTED_ISSUER,
            audience=EXPECTED_AUDIENCE,
            options={"verify_aud": False} # ハンズオン用: Audience検証はスキップ
        )
        logger.info("Offline validation successful.")
        return data

    except jwt.PyJWTError as e:
        logger.error(f"Offline Validation Error: {e}")
        return None

@app.route('/public')
def public():
    return jsonify({"message": "This is a public endpoint."})

@app.route('/secure')
def secure():
    """
    保護されたエンドポイント。
    設定されたモード(VALIDATION_MODE)に従ってトークンを検証します。
    """
    # 1. ヘッダーからトークン抽出
    auth_header = request.headers.get('Authorization', None)
    if not auth_header:
        return jsonify({"error": "Missing Authorization Header"}), 401

    # 2. Bearerスキームの確認とトークン抽出
    parts = auth_header.split()
    if parts[0].lower() != 'bearer':
        return jsonify({"error": "Invalid Header Type"}), 401
    elif len(parts) == 1:
        return jsonify({"error": "Token Missing"}), 401
    elif len(parts) > 2:
        return jsonify({"error": "Invalid Header Format"}), 401

    access_token = parts[1]
    token_payload = None

    # 2. モードに応じた検証ロジックの呼び出し
    if VALIDATION_MODE == 'introspect':
        logger.debug("Validating token using Introspection...")
        token_payload = introspect_token(access_token)
    else:
        logger.debug("Validating token using Offline (Stateless) verification...")
        token_payload = verify_token_offline(access_token)

    # 3. 検証結果の判定
    if not token_payload:
        return jsonify({"error": "Token is invalid or expired"}), 401

    # 4. 成功レスポンス
    return jsonify({
        "message": f"Access Granted via {VALIDATION_MODE.upper()} validation!",
        "user": token_payload.get('preferred_username'),
        "scope": token_payload.get('scope'),
        "iss": token_payload.get('iss'), # 確認用
        "mode": VALIDATION_MODE
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)