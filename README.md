# Minecraft Server Controller

## 概要
ブラウザから操作可能な Minecraft サーバー管理ツールです。  
- サーバー起動 / 停止 / 状態確認  
- ファイル・フォルダアップロード（自動反映）

## 使い方

### Docker 起動
```bash
cd minecraft-server-controller
docker compose up -d --build
```
## WebUI 操作

- `web/index.html` をブラウザで開く
- **Start / Stop / Status** ボタンでサーバー制御
- **Upload** ボタンでファイルまたはフォルダをアップロード

## API

- Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- エンドポイント:
  - `/start` - サーバー起動
  - `/stop` - サーバー停止
  - `/status` - サーバー状態取得
  - `/upload` - ファイル・フォルダアップロード

## 注意点

- 大容量ファイルやワールドの場合、アップロードに時間がかかります
- プラグインサーバーを使う場合、`docker-compose.yml` の `TYPE` を `PAPER` などに変更してください
