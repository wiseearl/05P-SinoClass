# index-hnsw.py 建置紀錄

## 目標

- 建立 [Index/index-hnsw.py](Index/index-hnsw.py)。
- 使用 [Index/config-hnsw.txt](Index/config-hnsw.txt) 作為參數檔。
- 讀取 [Index/db/data.db](Index/db/data.db) 內既有 Chroma embeddings，另建一份 HNSW 索引。
- 將 HNSW 索引輸出到 [Index/db/hnsw-index.bin](Index/db/hnsw-index.bin)，對照資訊輸出到 [Index/db/hnsw-manifest.json](Index/db/hnsw-manifest.json)。

## 設計判斷

1. 既有 [Index/index.py](Index/index.py) 已把 PDF chunk 與 embeddings 寫入 Chroma，因此 HNSW 版不需要重跑 PDF 解析與 embedding API。
2. [Index/config-hnsw.txt](Index/config-hnsw.txt) 已提供 `M`、`efConstruction`、`efSearch`、`Top-K`、`database_path`，最自然的控制面是從既有 Chroma collection 載入全部向量後建立 HNSW。
3. 由於 HNSW 二進位索引本身不保存 chunk_id 與 metadata 對照，額外輸出 [Index/db/hnsw-manifest.json](Index/db/hnsw-manifest.json) 保存 `label -> chunk_id -> metadata` 對映，避免後續查詢時遺失原始文件關聯。
4. 套件選用 `hnswlib`，空間採 `cosine`，與目前 Chroma 常見向量檢索語意相容。

## 實作內容

1. 在 [Index/index-hnsw.py](Index/index-hnsw.py) 新增與現有腳本一致的 `parse_config`、路徑解析與 collection 自動選擇流程。
2. 透過 `chromadb.PersistentClient` 開啟 [Index/config-hnsw.txt](Index/config-hnsw.txt) 指向的資料庫，使用 `collection.get(include=["embeddings", "metadatas"])` 取回全部向量與 metadata。
3. 以 `numpy.float32` 整理 embeddings，檢查筆數與維度後，用 `hnswlib.Index(space="cosine", dim=...)` 建立 HNSW index。
4. 套用設定檔中的 `M`、`efConstruction`、`efSearch`，並把資料列號當成內部 label。
5. 依設定檔中的 `Top-K` 對第一筆向量做一次 `knn_query` 自我檢查，確認索引可查詢，並把結果寫入 manifest。
6. 輸出二進位索引 [Index/db/hnsw-index.bin](Index/db/hnsw-index.bin) 與對照檔 [Index/db/hnsw-manifest.json](Index/db/hnsw-manifest.json)。

## 參數檔格式

目前使用的最小設定如下：

```txt
M=16
efConstruction=150
efSearch=75
Top-K=5
database_path=./db/data.db
```

可選擴充參數：

```txt
collection=private-data-chapter-index
output_index_path=./db/hnsw-index.bin
manifest_path=./db/hnsw-manifest.json
```

## 執行方式

在專案根目錄執行：

```powershell
d:/Code/CodingP/05P-SinoClass/.venv/Scripts/python.exe Index/index-hnsw.py
```

## 驗證項目

- 執行 `python -m py_compile Index/index-hnsw.py` 檢查語法。
- 執行 `python Index/index-hnsw.py` 檢查能否從 Chroma 成功建立 HNSW 索引。
- 抽查 [Index/db/hnsw-manifest.json](Index/db/hnsw-manifest.json) 是否包含 `count`、`dimension`、`self_check` 與 `items`。

## 驗證結果

- 已安裝 `hnswlib` 套件供 [Index/index-hnsw.py](Index/index-hnsw.py) 使用。
- 已執行 `python -m py_compile Index/index-hnsw.py`，語法檢查通過。
- 已執行 `python Index/index-hnsw.py`，成功從 [Index/db/data.db](Index/db/data.db) 讀取 `private-data-chapter-index` collection 並建立 HNSW 索引。
- 本次實際輸出為 `Vectors: 259`、`Dimension: 768`、`Self-check Top-K: 5`。
- HNSW 二進位索引已輸出到 [Index/db/hnsw-index.bin](Index/db/hnsw-index.bin)。
- 對照與自我檢查結果已輸出到 [Index/db/hnsw-manifest.json](Index/db/hnsw-manifest.json)。