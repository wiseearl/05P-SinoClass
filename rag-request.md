# RAG 問答程式建置紀錄

## 目標

建立 [Pdf2Embedding/rag-request.py](Pdf2Embedding/rag-request.py)，讀取 [Pdf2Embedding/config-rag-request.txt](Pdf2Embedding/config-rag-request.txt) 的參數，使用 [Pdf2Embedding/pdf2embedding.py](Pdf2Embedding/pdf2embedding.py) 產生的 ChromaDB 向量資料庫 [Pdf2Embedding/db/data.db](Pdf2Embedding/db/data.db) 做相似度檢索，將回答內容輸出到 [Pdf2Embedding/output.txt](Pdf2Embedding/output.txt)。

## 建立過程

1. 檢查 [Pdf2Embedding/pdf2embedding.py](Pdf2Embedding/pdf2embedding.py)，確認資料庫使用 `chromadb.PersistentClient`，資料預設寫入 [Pdf2Embedding/db/data.db](Pdf2Embedding/db/data.db)，collection 名稱預設為 `private-data`。
2. 檢查 [Pdf2Embedding/config-rag-request.txt](Pdf2Embedding/config-rag-request.txt)，確認目前至少提供 `question` 參數，可作為 RAG 查詢輸入。
3. 新增 [Pdf2Embedding/rag-request.py](Pdf2Embedding/rag-request.py)，實作以下流程：
   - 讀取 `config-rag-request.txt`
   - 呼叫 Ollama embedding API，將問題轉為查詢向量
   - 對 ChromaDB collection 進行相似度搜尋
   - 把檢索到的文件片段組成 prompt
   - 呼叫 Ollama 生成最終答案
   - 將答案與搜尋到的相近文件片段一併輸出到 [Pdf2Embedding/output.txt](Pdf2Embedding/output.txt)
4. 預設沿用 embedding 模型 `nomic-embed-text` 做檢索，生成模型則優先使用參數檔中的 `model`，若未提供則自動從本機 Ollama 模型中挑選第一個非 embedding 模型。
5. 實際執行程式，確認可從向量資料庫取回上下文並成功寫出答案檔案。
6. 修改 [Pdf2Embedding/rag-request.py](Pdf2Embedding/rag-request.py) 的輸出格式，讓 [Pdf2Embedding/output.txt](Pdf2Embedding/output.txt) 同時包含問題、回答與搜尋到的相近文件片段及頁碼資訊。
7. 擴充 [Pdf2Embedding/config-rag-request.txt](Pdf2Embedding/config-rag-request.txt)，加入 `model`、`embedding_model`、`base_url`、`collection`、`database_path`、`top_k`、`timeout` 等可調參數，讓查詢模型與檢索行為可直接透過設定檔調整。

## 參數檔格式

最小可用設定如下：

```txt
question=資料是什麼
```

可選擴充參數：

```txt
question=資料是什麼
model=qwen2.5:7b
embedding_model=nomic-embed-text
base_url=http://localhost:11434
collection=private-data
database_path=./db/data.db
top_k=4
timeout=120
```

目前專案中的 [Pdf2Embedding/config-rag-request.txt](Pdf2Embedding/config-rag-request.txt) 已擴充為可直接調整模型、資料庫位置與檢索筆數的版本。

## 執行方式

在專案根目錄執行：

```powershell
d:/Code/CodingP/05P-SinoClass/.venv/Scripts/python.exe Pdf2Embedding/rag-request.py
```

## 預期行為

- 程式會讀取 [Pdf2Embedding/config-rag-request.txt](Pdf2Embedding/config-rag-request.txt) 的問題內容。
- 程式會從 [Pdf2Embedding/db/data.db](Pdf2Embedding/db/data.db) 搜尋與問題最相近的文件片段。
- 程式會把答案與搜尋到的相近文件片段一併輸出到 [Pdf2Embedding/output.txt](Pdf2Embedding/output.txt)。
- 若本機沒有可用的生成模型，程式會回報錯誤並結束。

## 驗證結果

- 已執行 `python -m py_compile Pdf2Embedding/rag-request.py`
- 已執行 `python Pdf2Embedding/rag-request.py`
- 程式成功從 `private-data` collection 取回 4 筆相近片段
- 回答內容與相近文件片段已寫入 [Pdf2Embedding/output.txt](Pdf2Embedding/output.txt)
- 已更新 [Pdf2Embedding/config-rag-request.txt](Pdf2Embedding/config-rag-request.txt)，加入可調參數範例並以實際設定值保存