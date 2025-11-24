from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Docker環境内のKeycloak通信用URL
# ブラウザからはlocalhostだが、コンテナ間通信なのでサービス名(keycloak)を使用
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080")
REALM_NAME = os.environ.get("REALM_NAME", "demo-realm")
CLIENT_ID = "demo-client"
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "") # ★設定済みのSecret

INTROSPECT_URL = f"{KEYCLOAK_URL}/realms/{REALM_NAME}/protocol/openid-connect/token/introspect"

def introspect_token(access_token):
    """
    Keycloakのイントロスペクションエンドポイントを叩いてトークンを検証する
    """
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'token': access_token,
    }
    
    # ★ここが修正ポイント★
    # Hostヘッダーを強制的に 'localhost:8080' に設定し、Issuerの一貫性を保つ
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Host': 'localhost:8080'
    }
    
    try:
        response = requests.post(INTROSPECT_URL, data=payload, headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Introspection Error: {e}")
        return {'active': False}

@app.route('/public')
def public():
    return jsonify({"message": "This is a public endpoint."})

@app.route('/secure')
def secure():
    # 1. Authorizationヘッダーの取得
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

    # 3. イントロスペクションによる検証 (Phase 1)
    token_info = introspect_token(access_token)

    # 4. activeプロパティの確認 (RFC 7662)
    if not token_info.get('active'):
        return jsonify({"error": "Token is invalid or expired"}), 401

    # 成功時: 検証済み情報を返す（本番ではユーザ情報などを利用して処理を行う）
    return jsonify({
        "message": "Access Granted via Introspection!",
        "user": token_info.get('preferred_username'),
        "scope": token_info.get('scope'),
        "client_id": token_info.get('client_id') # 誰のために発行されたか
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)