# fatigue-analysis-kit

OpenFace + Kedro を使う疲労分析の実行環境です。

このディレクトリは `fatigued-face-space` 本体とは独立した実行環境です。OpenFace と Kedro のコンテナが `data/` を共有します。既存の Kedro プロジェクトの `data/` は使いません。

## 必要なもの

Ubuntu、Docker Engine と Docker Compose（`docker compose`）が必要です。Docker デーモンに接続できるユーザーで実行してください。OpenFace イメージの取得と Kedro イメージの作成にはネットワーク接続が必要です。

`fatigued-face-space/` は別リポジトリを参照する Git submodule です。このリポジトリが記録するコミットを取得してください。

```bash
git clone --recurse-submodules <fatigue-analysis-kitのURL>
```

通常の `git clone` で取得済みの場合は、次を実行します。

```bash
git submodule update --init --recursive
```

分析コードを開発する場合は `fatigued-face-space/` 内でブランチを選択し、変更をコミット・push します。その後、このリポジトリで submodule の参照変更をコミット・push してください。分析コードのコミットは先に push しないと、他の利用者が取得できません。

設定変更を反映するには、下記コマンドはこの README があるディレクトリで実行します。イメージ内のコードを更新する場合は、再度 `docker compose build kedro` を実行してください。

## 準備と実行

```bash
export STACK_UID=$(id -u) STACK_GID=$(id -g)
mkdir -p data/01_raw/movie data/01_raw/metadata_csv
docker compose build kedro
docker compose pull openface
```

1. `data/01_raw/movie/` に `.mp4` 動画を置きます。
2. `analyze` 以外のメタデータを使う分析では、`data/01_raw/metadata_csv/` にメタデータ CSV を置きます。v4 では少なくとも動画名を示す `Name` 列が必要です。必要な列は選択するパイプラインに依存します。
3. `fatigued-face-space/conf/<環境名>/` に実験設定を用意します。例えば `globals.yml` の `metadata_file: example` は `metadata_example.csv` を参照します。実験に必要なパラメータも指定してください。`ext_v4` には base にない `peak.height_multiplier` と `peak.rel_height` も必要です。設定は読み取り専用でコンテナにマウントされます。
4. 以下を実行します。環境名とパイプライン名は例です。

```bash
bash run.sh my_experiment ext_v4
```

`analyze` 以外を指定した場合、`run.sh` は OpenFace → `external_csv` → 指定した分析パイプラインの順に実行し、エラーが起きると停止します。特徴選択も含める場合は、必要な設定を用意した上で `ext_select` や `ext_select_v2` を指定できます。途中の処理を確認するには次のように個別実行できます。

```bash
docker compose run --rm openface
docker compose run --rm kedro run --env=my_experiment --pipeline=external_csv
docker compose run --rm kedro run --env=my_experiment --pipeline=ext_v4
```

### 動画を一本だけ処理する場合

```bash
bash run.sh my_experiment analyze
```

この場合は `select_movie` → 選択された一本の OpenFace 処理 → `analyze` の順で実行します。`external_csv` は実行しません。いずれかの段階で失敗すると後続は実行しません。未処理動画がない場合も選択段階で停止します。

選択結果はホストの `data/02_intermediate/movie_list.json` に保存されます。Kedro 内では `/app/data/02_intermediate/movie_list.json` として参照します。JSON の読み出しには Kedro イメージ内の Python を使い、ホストや OpenFace イメージへの追加インストールは不要です。

OpenFace には動画名を引数で渡します。動画は `/data/01_raw/movie/<動画名>.mp4` から読み込み、成功した CSV だけを `/data/02_intermediate/openface_temporary/<動画名>.csv` に移します。Kedro は同じ CSV を `/app/data/02_intermediate/openface_temporary/` から読み込み、選択した動画だけを分析します。

この実行経路の AU モデルは既存スクリプトと同じ `static` が既定です。`OPENFACE_AU_MODEL=dynamic bash run.sh my_experiment analyze` で dynamic を指定できます。OpenFace を呼ぶホスト側で指定するため、この経路では Kedro の `openface.au_model` は参照しません。

各段階を個別実行する場合は次のようにします。`sample` は選択済み JSON に記録された、拡張子を除いた動画名に合わせてください。

```bash
docker compose run --rm kedro run --env=my_experiment --pipeline=select_movie
docker compose run --rm openface sample static
docker compose run --rm kedro run --env=my_experiment --pipeline=analyze
```

同じ `data/` を使う実行は一つずつ行ってください。`movie_list.json` は今回の選択を保持する共通ファイルです。

既存の `openface` パイプラインは Docker コマンドを直接呼び出すため、この環境での OpenFace 実行には使いません。プロジェクトのコードや元のデータ構成は変更していません。

## 注意点

- `data/02_intermediate/openface_result/<動画名>.parquet` がある動画は処理済みとして OpenFace を省略します。再解析する場合は関連する既存結果を確認し、別の `data/` で実行することを推奨します。
- CSV 読み込み後は、その処理で読み込んだ一時 CSV だけを削除します。`analyze` は選択した一本の CSV のみを読み込み・削除します。CSV を Parquet に保存する途中で失敗した場合は、OpenFace を再実行して CSV を生成し直してください。
- OpenFace は既定で既存実装と同じ static AU モデルを使います。画像等の補助出力は一時領域に作られ、CSV のみ引き渡します。
- `latest` は将来更新される可能性があるため、厳密な再現性が必要になった時点で動作確認済みのイメージ digest を固定してください。
- データや実験設定には機微情報が含まれ得るため、公開リポジトリに追加する前に内容を確認してください。
