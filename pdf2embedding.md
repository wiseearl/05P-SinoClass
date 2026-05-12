# PDF 轉 Embedding 建置紀錄

## 目標

建立一支 Python 程式 [Pdf2Embedding/pdf2embedding.py](Pdf2Embedding/pdf2embedding.py)，讀取 [Pdf2Embedding/config-pdf2embedding.txt](Pdf2Embedding/config-pdf2embedding.txt) 中的 `source=./doc/private-data.pdf`，將 PDF 內容轉成 ChromaDB 格式的 embedding 資料庫，輸出到 [Pdf2Embedding/db/data.db](Pdf2Embedding/db/data.db)。

## 建立過程

1. 確認 [Pdf2Embedding/pdf2embedding.py](Pdf2Embedding/pdf2embedding.py) 目前為空檔，適合作為本次主流程實作點。
2. 檢查現有設定檔 [Pdf2Embedding/config-pdf2embedding.py](Pdf2Embedding/config-pdf2embedding.py)，確認已提供 `source=./doc/private-data.pdf`。
3. 依使用需求新增正式參數檔 [Pdf2Embedding/config-pdf2embedding.txt](Pdf2Embedding/config-pdf2embedding.txt)，並在程式中同時相容讀取 `.txt` 與既有 `.py` 版本。
4. 在 [Pdf2Embedding/pdf2embedding.py](Pdf2Embedding/pdf2embedding.py) 實作以下流程：
   - 自動尋找參數檔
   - 解析 `key=value` 設定
   - 依參數檔位置解析 `source` 相對路徑
   - 使用 `pypdf` 萃取 PDF 頁面文字
   - 依 `chunk_size` 與 `chunk_overlap` 切塊
   - 呼叫本機 Ollama embedding API
   - 使用 `chromadb.PersistentClient` 寫入 [Pdf2Embedding/db/data.db](Pdf2Embedding/db/data.db)
5. 安裝執行所需的 Python 套件 `pypdf` 與 `chromadb`。
6. 執行語法檢查與實際腳本執行驗證，首次執行時發現 Ollama 回傳 `model "nomic-embed-text" not found`。
7. 依錯誤訊息執行 `ollama pull nomic-embed-text` 下載 embedding 模型。
8. 確認終端輸出包含 `verifying sha256 digest`、`writing manifest` 與 `success`，表示模型已成功安裝。

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
collection=private-data
chunk_size=1000
chunk_overlap=150
timeout=120
```

## 執行方式

在專案根目錄執行：

```powershell
d:/Code/CodingP/05P-SinoClass/.venv/Scripts/python.exe Pdf2Embedding/pdf2embedding.py
```

## 預期行為

- 程式會優先讀取 [Pdf2Embedding/config-pdf2embedding.txt](Pdf2Embedding/config-pdf2embedding.txt)。
- 若 `.txt` 不存在，仍可回退讀取 [Pdf2Embedding/config-pdf2embedding.py](Pdf2Embedding/config-pdf2embedding.py)。
- 產出的 ChromaDB 持久化目錄為 [Pdf2Embedding/db/data.db](Pdf2Embedding/db/data.db)。
- 若本機 Ollama 未啟動或缺少 embedding 模型，程式會回報錯誤並結束。

## 驗證結果

- 已執行 `python -m py_compile Pdf2Embedding/pdf2embedding.py`
- 已執行 `python Pdf2Embedding/pdf2embedding.py`，首次失敗原因為本機缺少 `nomic-embed-text` 模型
- 已執行 `ollama pull nomic-embed-text`
- Ollama 回傳 `success`，模型下載完成

## 模型安裝指令

若本機尚未安裝 embedding 模型，請先在專案根目錄執行：

```powershell
ollama pull nomic-embed-text
```

本次實際執行結果為成功，終端最後輸出如下重點：

```text
verifying sha256 digest
writing manifest
success
```