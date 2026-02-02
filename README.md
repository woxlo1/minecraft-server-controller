# Minecraft Server Controller v4.0

## 概要
ブラウザから操作可能な Minecraft サーバー管理ツールです。  
プレイヤー名ベースの認証、ホワイトリスト、OP管理、プラグイン管理に対応しました。

## 新機能（v4.0）

### 1. プレイヤー名ベースの認証
- プレイヤー名とAPIキーを紐付け
- Role（player / admin）による権限管理
- 各プレイヤーが自分専用のAPIキーを持つ

### 2. ホワイトリスト管理
- プレイヤーの追加/削除
- ホワイトリストの有効化/無効化
- 登録済みプレイヤー一覧表示

### 3. Operator（OP）管理
- プレイヤーへのOP権限付与/削除
- 管理者権限が必要

### 4. プラグイン管理（PAPER/SPIGOT用）
- プラグイン一覧表示
- プラグイン(.jar)のアップロード
- プラグインの削除
- プラグインのリロード

## 使い方

### 1. Docker 起動
```bash
cd minecraft-server-controller
docker compose up -d --build
```

### 2. 初回セットアップ

#### Root APIキーの確認
`docker-compose.yml`で設定した`ROOT_API_KEY`を確認してください。

#### プレイヤー登録
1. ブラウザで `index.html` を開く
2. **プレイヤー登録**セクションで：
   - Minecraftプレイヤー名を入力
   - Roleを選択（player または admin）
   - Root APIキーを入力して登録
3. 発行されたAPIキーを保存

#### APIキーの設定
1. **API Key**セクションに発行されたAPIキーを入力
2. 「保存」をクリック
3. 「自分の情報を確認」で正しく認証されているか確認

### 3. WebUI 操作

#### サーバー制御
- **Start / Stop / Status** ボタンでサーバー制御

#### ホワイトリスト管理
- プレイヤー名を入力して追加/削除
- ホワイトリストの有効化/無効化
- リスト表示で登録済みプレイヤーを確認

#### Operator 管理（管理者のみ）
- プレイヤー名を入力してOP権限を付与/削除

#### プラグイン管理（管理者のみ）
- プラグイン一覧を表示
- .jarファイルをアップロード
- 不要なプラグインを削除
- プラグインをリロード（再起動不要）

#### その他
- **Upload** ボタンでファイルまたはフォルダをアップロード
- **Backup** でワールドデータをバックアップ
- **Console** でサーバーコマンドを実行

## API

- Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)

### 主要エンドポイント

#### 認証
- `POST /auth/keys` - APIキー発行（Root専用）
- `GET /auth/keys` - APIキー一覧（Root専用）
- `GET /auth/keys/my` - 自分のAPIキー情報
- `DELETE /auth/keys/{key}` - APIキー削除（Root専用）

#### サーバー制御
- `POST /start` - サーバー起動
- `POST /stop` - サーバー停止
- `GET /status` - サーバー状態取得

#### ホワイトリスト
- `POST /whitelist/add/{player}` - プレイヤー追加
- `POST /whitelist/remove/{player}` - プレイヤー削除
- `GET /whitelist` - ホワイトリスト表示
- `POST /whitelist/enable` - ホワイトリスト有効化
- `POST /whitelist/disable` - ホワイトリスト無効化

#### Operator
- `POST /op/add/{player}` - OP権限付与（管理者専用）
- `POST /op/remove/{player}` - OP権限削除（管理者専用）

#### プラグイン
- `GET /plugins` - プラグイン一覧
- `POST /plugins/upload` - プラグインアップロード（管理者専用）
- `DELETE /plugins/{filename}` - プラグイン削除（管理者専用）
- `POST /plugins/reload` - プラグインリロード（管理者専用）

#### その他
- `POST /upload` - ファイル・フォルダアップロード
- `POST /backup` - バックアップ作成
- `GET /logs` - サーバーログ取得
- `POST /exec` - コンソールコマンド実行
- `GET /players` - オンラインプレイヤー一覧
- `GET /audit/logs` - 操作ログ（Root専用）

## 権限レベル

### Root
- すべての操作が可能
- APIキーの発行・管理
- 監査ログの閲覧

### Admin
- サーバー制御
- プラグイン管理
- OP権限の付与/削除
- ホワイトリスト管理
- ファイルアップロード
- バックアップ

### Player
- サーバー状態確認
- ホワイトリスト管理
- ログ閲覧
- プレイヤー情報閲覧

## 注意点

- 大容量ファイルやワールドの場合、アップロードに時間がかかります
- プラグインサーバーを使う場合、`docker-compose.yml` の `TYPE` を `PAPER` などに変更してください
- プラグインのアップロード/削除後はサーバーの再起動が推奨されます
- APIキーは再発行できないため、安全に保管してください
- Root APIキーは絶対に公開しないでください

## セキュリティ

- すべてのAPI操作はAPIキーで認証されます
- 操作ログは監査のために記録されます
- 権限レベルにより操作が制限されます
- SQLiteデータベースは `/data` ディレクトリに永続化されます

## トラブルシューティング

### APIキーが動作しない
1. Root APIキーで `/auth/keys/my` にアクセスして認証状態を確認
2. データベースファイル `/data/api.db` の権限を確認

### プラグインが反映されない
1. サーバーを再起動してください
2. プラグインリロードを試してください
3. サーバーログでエラーを確認してください

### データベースが初期化される
`docker-compose.yml` で `/data` ディレクトリがマウントされているか確認してください