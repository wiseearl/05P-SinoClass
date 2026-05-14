# Index PDF 轉 Embedding 建置紀錄

## 目標

建立 [Index/index.py](/d:/Code/CodingP/05P-SinoClass/Index/index.py)，讀取 [Index/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Index/config-metadata.txt) 的參數，將 [Index/doc/private-data.pdf](/d:/Code/CodingP/05P-SinoClass/Index/doc/private-data.pdf) 解析為帶有法規章節 metadata 的 Chroma 向量資料，輸出到 [Index/db/data.db](/d:/Code/CodingP/05P-SinoClass/Index/db/data.db)，並額外建立一份以章節為索引的 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json)。

## 建置過程

1. 檢查 [Index/config-index.txt](/d:/Code/CodingP/05P-SinoClass/Index/config-index.txt) 與 [Metadata/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Metadata/config-metadata.txt)，確認兩者都以 `source=./doc/private-data.pdf` 作為最小設定，因此 Index 版可採相同參數格式。
2. 新增 [Index/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Index/config-metadata.txt)，讓 `index.py` 直接使用你指定的 `config-metadata.txt` 檔名，且來源路徑維持 Index 目錄下的 `./doc/private-data.pdf`。
3. 在 [Index/index.py](/d:/Code/CodingP/05P-SinoClass/Index/index.py) 重用 [Metadata/metadata.py](/d:/Code/CodingP/05P-SinoClass/Metadata/metadata.py) 已驗證的 PDF 清洗、雙欄內容過濾、章節辨識、chunking、embedding 與 Chroma 寫庫流程。
4. 保留每個 chunk 開頭的 `[法規章節] ...` 前綴，並沿用 Chroma metadata 中的 `chapter`、`page`、`chunk_index`、`start_char`、`end_char` 欄位，讓 chunk 本身能直接標示所屬法規章節。
5. 額外在 `index.py` 中建立章節索引，把同一章節下的 `pages`、`chunk_ids`、`chunk_count` 與 `preview` 整理成 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json)，讓章節可直接作為索引入口。
6. Index 版向量資料庫固定輸出到 [Index/db/data.db](/d:/Code/CodingP/05P-SinoClass/Index/db/data.db)，避免與 [Metadata/db/data.db](/d:/Code/CodingP/05P-SinoClass/Metadata/db/data.db) 混用。
7. 依索引結果檢查後，發現 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json) 前段仍會混入第 1、2 頁的目錄與前置說明內容，因此在 [Index/index.py](/d:/Code/CodingP/05P-SinoClass/Index/index.py) 改為直接把前兩頁的 chunk 全數排除在章節索引之外，只保留第 3 頁之後的索引輸出。

## 參數檔格式

最小可用設定如下：

```txt
source=./doc/private-data.pdf
```

可選擴充參數：

```txt
source=./doc/private-data.pdf
model=nomic-embed-text
base_url=http://localhost:11434
collection=private-data-chapter-index
chunk_size=1000
chunk_overlap=150
timeout=120
```

## 執行方式

在專案根目錄執行：

```powershell
d:/Code/CodingP/05P-SinoClass/.venv/Scripts/python.exe Index/index.py
```

## 預期行為

- 程式優先讀取 [Index/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Index/config-metadata.txt)，若本地檔案不存在才回退讀取 [Metadata/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Metadata/config-metadata.txt)。
- 程式會解析雙欄 PDF，盡量保留中文法規正文並在 chunk 開頭加入對應章節標記。
- 向量資料會寫入 [Index/db/data.db](/d:/Code/CodingP/05P-SinoClass/Index/db/data.db)。
- 章節索引會寫入 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json)。

## 驗證項目

- 執行 `python -m py_compile Index/index.py` 檢查語法。
- 執行 `python Index/index.py` 驗證實際建立向量資料庫與章節索引。
- 抽查 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json) 是否含有 `chapter_count`、`chapters` 與各章節的 `pages`、`chunk_ids`。

## 驗證結果

- 已執行 `python -m py_compile Index/index.py`，語法檢查通過。
- 已執行 `python Index/index.py`，成功建立 `private-data-chapter-index` collection。
- 本次實際輸出為 `Segments: 259`、`Chunks: 259`，資料庫位置為 [Index/db/data.db](/d:/Code/CodingP/05P-SinoClass/Index/db/data.db)。
- 章節索引已輸出到 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json)，目前 `chapter_count` 為 `70`。
- 已抽查 Chroma 文件與 metadata，確認 chunk 文字開頭含有 `[法規章節]`，metadata 內含 `chapter`、`page`、`chunk_index`、`start_char`、`end_char`。
- 已調整 [Index/index.py](/d:/Code/CodingP/05P-SinoClass/Index/index.py) 的索引輸出邏輯，重新執行後應可把目錄頁條目從 [Index/db/chapter-index.json](/d:/Code/CodingP/05P-SinoClass/Index/db/chapter-index.json) 排除，不影響 [Index/db/data.db](/d:/Code/CodingP/05P-SinoClass/Index/db/data.db) 中的原始 chunk 與 metadata。