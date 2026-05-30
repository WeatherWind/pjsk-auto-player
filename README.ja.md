# PJSK Auto Player — CV 自動化研究ツール

[![zh-CN](https://img.shields.io/badge/README-中文-lightgrey)](README.md)
[![en](https://img.shields.io/badge/README-English-lightgrey)](README.en.md)
[![ja](https://img.shields.io/badge/README-日本語-blue)](README.ja.md)

> ADB + OpenCV を使用したコンピュータビジョンと自動化制御の研究プロジェクト。
> MAA (MaaAssistantArknights) + ALAS (AzurLaneAutoScript) + MaaFramework のアーキテクチャを参考に設計。

---

## 🚀 クイックスタート — すぐに使える

### 方法 1: ダブルクリックで起動 (推奨)

| OS | 操作 |
|----|------|
| **macOS** | `PJSK Auto Player.command` をダブルクリック |
| **Windows** | `run.bat` をダブルクリック |
| **Linux** | `run.sh` をダブルクリック、または端末で `./run.sh` を実行 |

初回起動時に依存関係を自動インストールし、セットアップウィザードが開きます。以降はダブルクリックでネイティブデスクトップ GUI が直接起動します。

### 方法 2: コマンドライン

```bash
python main.py              # 🖥️ ネイティブデスクトップ GUI (デフォルト)
python main.py desktop      # 🌐 デスクトップモード — ブラウザパネルを自動起動
python main.py start        # 単発実行
python main.py auto         # 連続実行 (リザルト処理とリトライを自動化)
python main.py setup        # セットアップウィザード
```

---

## ✨ バージョンハイライト

| バージョン | 特徴 |
|-----------|------|
| **v5.7.1** | 🐛 4 つの重要な修正 — OCR セキュリティ脆弱性修正 + 不要なクリア削除 + ガウス分布補完 + コード整理 |
| **v5.7.0** | ⚡ ゼロ割り当てフレームバッファ — scrcpy の per-frame malloc を排除、CPU 割り当てコスト 0 に |
| **v5.6.0** | 🔐 操作パターン多様性 — Session Fingerprint + ガウス分布ジッター + SAFE/PRECISION モード |
| **v5.5.0** | 🛡️ 閉塞検出と自動復旧 — 5 段階復旧ステートマシン + ヘルスハートビート + ポップアップ処理 |
| **v5.4.0** | ⚡ パフォーマンス最適化 — ホットパスキャッシュ + フレーム差分スキップ + termios キャッシュ |
| **v5.3.0** | 🎮 ゲーム内設定の自動読み取り + マルチサーバー対応 (JP/TW/CN/KR/EN) + 自動キャリブレーション |
| **v5.2.0** | ⚡ 非同期キャプチャ + Raw ADB + バッチタッチ — レイテンシ大幅削減 |
| **v5.1.0** | 🌍 i18n 国際化 (中/英/日) + 📱 PWA モバイルパネル + 🌓 デュアルテーマ + 🧪 ユニットテスト |
| **v5.0.0** | 🖥️ MAA スタイルネイティブデスクトップ GUI + 操作の自然化 + イベントタイプ認識 |
| **v4.11.0** | 🖥️ すぐ使える: デスクトップアプリ + ブラウザ自動起動 + 初回ウィザード + システムトレイ |
| **v4.10.0** | 🧬 ALAS 深層統合: cached_property/Resource/色前処理/Benchmark/設定スキーマ |
| **v4.9.0** | 🏗️ MAA/ALAS 融合アーキテクチャ: Pipeline V2 + マルチアルゴリズムシーン判定 + Web ダークパネル + 階層的例外 + デーモン |

---

## 🔥 主な機能

### 🎯 予測エンジン
タイミングベースの予測システム: 判定線上のノーツを検出 → 移動速度を追跡 → 到達時間を計算 → 正確にトリガー。
ADB リンクの 100-300ms の伝送遅延を補償し、受動的応答から能動的予測へ。

### ⚡ 画面キャプチャ高速化 (v5.2.0)
- **非同期キャプチャ**: producer-consumer モデル、バックグラウンドスレッドが継続的にキャプチャ
- **Raw ADB**: `adb exec-out screencap` 生 RGBA 形式、PNG より 2-3 倍高速
- **スマートフォールバック**: scrcpy → raw ADB → PNG ADB 自動選択

### 🧠 Pipeline V2 エンジン (MAA 参考)
- **JSON タスク設定駆動** — 認識→アクション→遷移の宣言的パイプライン
- **@タスク継承** — `"ClickOK@ClickSelf"` で親設定を再利用
- **ノードライフサイクル** — `pre_wait_freezes → pre_delay → action → post_wait_freezes → post_delay`
- **プラグインシステム** — AOP スタイル、タスク前後にログ/統計/エラー処理を自動注入

### 🎮 ゲーム内設定の自動読み取り (v5.3.0)
ゲーム内の LIVE 設定画面に自動遷移し、`タイミング調整` と `ノーツ速度` を OCR で読み取り、ソフトウェアパラメータに自動マッピングして予測エンジンをキャリブレーションします。

- **自動キャリブレーション**: `タイミング調整` → `advance_ms` / `ノーツ速度` → `velocity_factor` 自動換算
- **6 サーバー対応**: JP / TW / CN / KR / EN + 自動検出 (パッケージ名/OCR ラベル/手動)
- **ゼロ設定起動**: デフォルトで有効、初回実行時に自動読み取り → 以降はキャッシュを再利用
- **単独コマンド**: `python main.py read-settings --server jp`

```
┌──────────────────────────────────────────────┐
│  ゲーム内 LIVE 設定                            │
│  タイミング調整: +5   →   advance_ms -5ms      │
│  ノーツ速度:    10.5   →   velocity × 1.05     │
│  ─────────────────────────────────────────   │
│  config.yaml に自動書込 + 予測エンジン更新     │
└──────────────────────────────────────────────┘
```

### 🎲 操作ランダム化
人間の操作特性をシミュレート: ベジェ曲線スワイプ、タイミング摂動 ±15ms、座標オフセット ±5px、ランダムミス 0.1%

### 🎮 実行戦略
- **AP** — 高精度トリガー戦略
- **FC** — 安定性重視戦略
- **LIVE** — 基本クリア戦略
- **混合** — スマート切替戦略 (70% FC + 25% AP + 5% LIVE)

### ⚡ PID 適応遅延
毎回の実行終了後、実際のトリガー先行量に基づいて遅延補償を自動微調整し、最適値に徐々に収束。

### 📡 マルチバックエンドコントローラー
- **scrcpy 60 FPS** — ビデオストリーム高速キャプチャ
- **Minitouch <5ms** — 超低遅延タッチ
- **Raw ADB** — 生 RGBA キャプチャ
- **ADB フォールバック** — 最適バックエンドを自動検出

### 🛡️ 階層的例外システム (ALAS 参考)
| 例外 | 回復戦略 |
|------|---------|
| `GameStuckError` | 画面フリーズ → 再起動 |
| `GameBugError` | 状態異常 → プロセス強制終了・再起動 |
| `GamePageUnknownError` | 不明なページ → 戻る |
| `ConnectionLostError` | 接続切断 → 再接続待機 |
| `TooManyClickError` | 無限ループ防止 → タスク停止 |

---

## 前提条件

- Python 3.9+
- Android デバイス (いずれか):
  - **実機**: USB デバッグ有効、USB ケーブル接続
  - **エミュレーター**: MuMu Player 12 (推奨) または LDPlayer 9
- ADB (自動検出または手動インストール)

## 接続方法

### 方法 A: 実機 (USB 直結)
```bash
# 1. スマホで USB デバッグを有効にする (開発者オプション内)
# 2. USB ケーブルで PC に接続
# 3. 接続確認
adb devices
# 表示されるはず: <serial>  device

# 4. セットアップウィザードを実行
python main.py setup
```

### 方法 B: MuMu Player 12 (推奨)
```bash
# 1. MuMu Player 12 をダウンロード: https://mumu.163.com/
# 2. エミュレーターに PJSK をインストール (Google Play / QooApp / APK)
# 3. エミュレーター設定 → その他設定:
#    - ROOT 権限を無効化
#    - 解像度: 1280x720 (推奨)
#    - ADB デバッグを有効化
# 4. エミュレーター ADB に接続
adb connect 127.0.0.1:7555   # MuMu 12 デフォルトポート

# 5. 接続確認
adb devices

# 6. セットアップウィザードを実行
python main.py setup
```

> ⚠️ **エミュレーター注意事項**:
> - 日服 (jp) は検出が厳しいため、MuMu 12 Android 9 イメージを推奨
> - エミュレーター内で ROOT を有効にしないでください

---

## インストール (開発者向け)

```bash
git clone https://github.com/WeatherWind/pjsk-auto-player.git
cd pjsk-auto-player
pip install -r requirements.txt
```

```bash
# 1. 初回 → セットアップウィザード
python main.py setup

# 2. キャリブレーション
python main.py calibrate

# 3. 実行開始
python main.py start

# 4. または Web ダッシュボードを起動 (ブラウザ http://localhost:8080)
python main.py desktop
```

---

## コマンドリファレンス

| コマンド | 説明 |
|---------|------|
| `python main.py` | ネイティブデスクトップ GUI (デフォルト) |
| `python main.py start` | 単発実行 |
| `python main.py auto` | 連続実行 |
| `python main.py calibrate` | ワンクリックキャリブレーション |
| `python main.py read-settings` | ゲーム内設定を読み取り (v5.3.0) |
| `python main.py setup` | セットアップウィザード |
| `python main.py status` | デーモン状態確認 |
| `python main.py stop` | デーモン停止 |

---

## 🚦 CI/CD

| ワークフロー | トリガー | 説明 |
|-------------|---------|------|
| **ci.yml** | push (非main) / PR | lint + pytest (58 tests) |
| **auto-release.yml** | push to main | VERSION を自動読み取り → タグ作成 → ビルドトリガー |
| **build.yml** | tag (v*.*.*) | PyInstaller ビルド → GitHub Release |

---

## 免責事項

本ソフトウェアは学習・研究目的のみです。本ソフトウェアの使用は Project Sekai (SEGA/Colorful Palette) の利用規約に違反する可能性があります。ユーザーはすべてのリスクと責任を負うものとします。開発者はアカウント停止やその他の結果について一切の責任を負いません。

詳細は [TERMS.md](TERMS.md) を参照してください。

---

## ライセンス

MIT License
