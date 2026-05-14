# Metadata PDF 轉 Embedding 建置紀錄

## 目標

建立 [Metadata/metadata.py](/d:/Code/CodingP/05P-SinoClass/Metadata/metadata.py)，讀取 [Metadata/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Metadata/config-metadata.txt) 的參數，將 [Metadata/doc/private-data.pdf](/d:/Code/CodingP/05P-SinoClass/Metadata/doc/private-data.pdf) 解析成帶有法規章節資訊的 Chroma 向量資料，並輸出到 [Metadata/db/data.db](/d:/Code/CodingP/05P-SinoClass/Metadata/db/data.db)。

## 建置過程

1. 參考既有 [Pdf2Embedding/pdf2embedding.py](/d:/Code/CodingP/05P-SinoClass/Pdf2Embedding/pdf2embedding.py) 的設定檔解析、PDF 萃取、Ollama embedding 與 Chroma 寫庫流程，作為 Metadata 版的基底。
2. 抽樣檢查 [Metadata/doc/private-data.pdf](/d:/Code/CodingP/05P-SinoClass/Metadata/doc/private-data.pdf) 的 `pypdf` 萃取結果，確認文件是中英雙欄混排，且章節標題會以中文標題行保留在文字輸出中。
3. 在 [Metadata/metadata.py](/d:/Code/CodingP/05P-SinoClass/Metadata/metadata.py) 新增中文內容清洗流程，過濾英文字欄、頁首頁尾與版本日期等噪音。
4. 新增章節辨識規則，追蹤 `附表`、`第 X 部`、`第 X 分部` 與 `X. 第 X 原則` 等標題，組成目前 chunk 所屬的法規章節路徑。
5. 調整 chunking 流程，改為先依章節切成 segment，再做字元切塊，避免同一個 chunk 橫跨不同章節時 metadata 錯置。
6. 在每個 chunk 文字開頭加入 `[法規章節] ...` 前綴，並同步把 `chapter` 寫入 Chroma metadata 欄位，方便檢索與後續引用。
7. 向量資料庫固定輸出到 [Metadata/db/data.db](/d:/Code/CodingP/05P-SinoClass/Metadata/db/data.db)，避免覆寫既有 Pdf2Embedding 的資料庫。

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
collection=private-data-metadata
chunk_size=1000
chunk_overlap=150
timeout=120
```

## 執行方式

在專案根目錄執行：

```powershell
d:/Code/CodingP/05P-SinoClass/.venv/Scripts/python.exe Metadata/metadata.py
```

## 預期行為

- 程式讀取 [Metadata/config-metadata.txt](/d:/Code/CodingP/05P-SinoClass/Metadata/config-metadata.txt) 的 `source` 與可選參數。
- 程式只保留 PDF 中的中文法規內容，盡量排除雙欄中的英文重複內容與頁面雜訊。
- 每個 chunk 開頭都會加入對應章節標記，例如 `[法規章節] 附表 1 保障資料原則 > 1. 第 1 原則 —— 收集個人資料的目的及方式`。
- Chroma metadata 會同步記錄 `chapter`、`page`、`chunk_index`、`start_char`、`end_char`。
- 向量資料庫寫入 [Metadata/db/data.db](/d:/Code/CodingP/05P-SinoClass/Metadata/db/data.db)。

## 驗證項目

- 執行 `python -m py_compile Metadata/metadata.py` 檢查語法。
- 執行 `python Metadata/metadata.py` 驗證實際建立向量資料庫。
- 以 Chroma 抽查至少一筆文件，確認 chunk 文字開頭含有 `[法規章節]`，且 metadata 欄位含 `chapter`。

## 驗證結果

- 已執行 `python -m py_compile Metadata/metadata.py`，語法檢查通過。
- 已執行 `python Metadata/metadata.py`，成功建立 `private-data-metadata` collection。
- 本次實際輸出為 `Segments: 259`、`Chunks: 259`，資料庫位置為 [Metadata/db/data.db](/d:/Code/CodingP/05P-SinoClass/Metadata/db/data.db)。
- 已以 Chroma 抽查文件內容，確認 chunk 文字開頭帶有 `[法規章節]` 前綴，metadata 含有 `chapter`、`page`、`chunk_index`、`start_char`、`end_char`。