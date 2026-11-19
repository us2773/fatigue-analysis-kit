# 動画受信・分析API

最初の段階として、動画を受信・保存し、動画ストリームを確認してからサンプルJSONを返します。
**現在は実分析を行いません。返す2.18は固定のサンプル値です。**
既存のOpenFace/Kedro用Docker構成と、分析サブモジュールは変更していません。

## 起動

Python 3.11以上とFFmpegの`ffprobe`が必要です。Docker版にはffprobeを含めています。
リポジトリのルートで次を実行します。

```bash
export STACK_UID=$(id -u) STACK_GID=$(id -g)
mkdir -p data/01_raw/movie
docker compose -f compose.api.yaml up --build api
```

初期設定では`http://127.0.0.1:8000`から接続できます。研究室LANの別PCから使う場合は、
サーバ上で`FF_API_HOST=0.0.0.0`を設定して同じコマンドで起動し、サーバのLANアドレスへ接続します。
認証・HTTPSを実装する前の、研究室内の疎通確認用です。

Dockerを使わない開発用の起動方法は次の通りです。ffprobeは別途インストールしてPATHへ追加してください。

```bash
python -m venv .venv-api
# Linux/macOS: source .venv-api/bin/activate
# Windows PowerShell: .\.venv-api\Scripts\Activate.ps1
python -m pip install -e './api[test]'
python -m uvicorn fatigue_analysis_api.app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

最小構成では**必ず1ワーカー・1プロセス**で起動します。
処理中に別の分析依頼が来た場合はHTTP 409 / `SERVER_BUSY`を返します。キューや並列処理は後続の課題です。

## リクエスト

| API | 用途 |
| --- | --- |
| `GET /health` | 接続確認。`analysis_mode: "sample"`と、選択可能なパイプラインを返す。 |
| `POST /v1/analyses?pipeline=daily` | 動画本体を送信し、レスポンスJSONを受け取る。 |

動画は**HTTPリクエスト本文にバイナリとして直接**送ります。multipartやbase64にはしません。
`Content-Type`はMP4なら`video/mp4`、MOVなら`video/quicktime`です。
現在選択できるパイプラインは`daily`だけで、追加のクエリ項目や重複指定は拒否します。
分析パラメータを変更するAPIは用意しません。

```bash
curl --fail-with-body \
  -X POST 'http://127.0.0.1:8000/v1/analyses?pipeline=daily' \
  -H 'Content-Type: video/mp4' \
  --data-binary '@sample.mp4'
```

Windows PowerShellでは`curl.exe`を使い、上記を1行で実行できます。
Tkinter側では、ファイルを開いてHTTPライブラリへ本文として渡せば同じリクエストになります。

受信した動画は`data/01_raw/movie/<analysis_id>.mp4`または`.mov`に保存します。
`analysis_id`はサーバ発行のUUIDで、レスポンスとログにも同じIDが入ります。
元のファイル名は送る必要がなく、同名ファイルの上書きやファイル名に含まれる個人情報の記録を避けられます。
既存の分析用データを誤って処理しないよう、この段階では`run.sh`を呼び出しません。

## レスポンス

正常時はHTTP 200で、既に取り決めたJSON構造を返します。

```json
{
  "schema_version": "1.0",
  "analysis_id": "サーバ発行のID",
  "status": "succeeded",
  "result": {
    "features": [
      {
        "id": "AU02_trend_mean",
        "label": "AU02 トレンド平均",
        "value": 2.18,
        "describe": null,
        "error": null
      }
    ],
    "summary": {"message": null, "advise": null}
  },
  "error": null,
  "metadata": {
    "pipeline": "daily",
    "analysis_version": "sample-v1",
    "parameter_set_id": null
  }
}
```

`X-Analysis-Mode: sample`ヘッダーと`metadata.analysis_version`でサンプル応答を識別できます。
Tkinterアプリは、正常時・失敗時ともレスポンス本文をそのまま表示してください。

エラー時も同じ外側の構造で、`status: "failed"`、`result: null`、
`error: {"code": "...", "message": "...", "stage": "...", "detail": null}`を返します。

| HTTP | 主なエラーコード | 状況 |
| --- | --- | --- |
| 400 | `INVALID_PIPELINE`, `EMPTY_VIDEO`, `INVALID_CONTENT_LENGTH`, `UPLOAD_INTERRUPTED` | リクエストの不備・送信中断 |
| 409 | `SERVER_BUSY` | 別の動画を処理中 |
| 413 | `VIDEO_TOO_LARGE` | 動画容量が上限を超過 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 対応しないContent-Type |
| 422 | `INVALID_VIDEO`, `VIDEO_VALIDATION_TIMEOUT` | 動画ストリームの確認失敗 |
| 503 | `VIDEO_VALIDATOR_UNAVAILABLE` | ffprobeがない |
| 500 | `INTERNAL_ERROR` | 保存・分析アダプターなどの処理失敗 |

ffprobeによる確認は、動画ストリームと幅・高さが読み取れるかの検査です。
顔の有無、画質、全フレームのデコード可否はこの段階では判定しません。

## 設定とデータの扱い

| サーバ環境変数 | 既定値 | 用途 |
| --- | --- | --- |
| `FF_API_DATA_DIR` | 作業ディレクトリの`data`（Docker内は`/data`） | 動画の保存先 |
| `FF_API_MAX_UPLOAD_BYTES` | `268435456`（256 MiB） | 動画本体の上限。Content-Lengthなしでも適用 |
| `FF_API_FFPROBE` | `ffprobe` | ffprobe実行ファイルのパス。Docker版では変更不要 |
| `FF_API_HOST` | `127.0.0.1` | Composeでの公開先アドレス |

- 保存が途中で失敗したデータや、動画確認に失敗したファイルは削除します。
- 確認済みの動画はサーバに残ります。不要になった動画は管理者が保存先から削除してください。
- `data/`、撮影動画、仮想環境、個人用`.env`、ログはGitとDockerのビルド対象から除外します。
- アプリのログは発行ID・ステータス・エラーコードを中心とし、動画本体・元のファイル名・個人識別情報を出しません。
  例外の詳細はクラス名だけを返し、ローカルパスや例外文は返しません。起動例ではHTTPアクセスログも無効にしています。

## 実分析への接続

`app.py`が通信、`storage.py`が受信ファイルの保存、`video.py`が動画確認、`analysis.py`が分析アダプター、
`models.py`がレスポンスの型を担当します。
`create_app(analyzer=...)`に`Analyzer`インターフェースを満たす実装を渡すことで、
通信と保存の処理を変えずに`SampleAnalyzer`を置き換えられます。

アダプターが返す特徴量の一部だけ失敗した場合は`partial`として、数値と特徴量別のエラーを保持します。
有効な値が一つもない場合も、特徴量別の失敗情報は残して`failed`を返します。
実分析の呼び出し方法・版と固定設定IDの管理は、分析モジュール側との接続時に実装します。

## テスト

```bash
python -m pytest api/tests -q
```

動画の保存、容量上限、エラー応答、パラメータ上書きの拒否、同時依頼の拒否、部分成功を確認します。
ffmpegとffprobeがある環境では、単色の人工動画を一時生成して、動画確認までの結合テストも行います。
研究データ・撮影動画・個人情報をテスト用ファイルとしてコミットする必要はありません。
