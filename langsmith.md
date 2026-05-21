# LangSmith 監控建置紀錄

## 目標

在 Index 目錄新增 langsmith.py，讀取 config-langsmith.txt，依 execute 設定執行目標腳本，使用 LangSmith 套件包裹執行流程，並將追蹤摘要、stdout、stderr 與時間線寫入 log-langsmith.txt。

## 設計決策

1. 設定檔格式

沿用現有腳本的 key=value 或 key:value 解析方式，預設讀取 Index/config-langsmith.txt。

2. 執行模型

langsmith.py 不重寫 req-rrf.py 內部邏輯，而是以 subprocess 啟動目標腳本。這樣可以保留 req-rrf.py 既有行為，並把 LangSmith 監控集中在外層 wrapper。

3. 監控內容

log-langsmith.txt 會保存：

- 執行命令與工作目錄
- 開始時間、結束時間、耗時、return code
- LangSmith 可用性、追蹤模式、run_id 與 trace_id
- stdout 與 stderr 完整內容
- 依時間排序的 stdout/stderr timeline
- JSON 區塊，方便後續程式讀取

4. LangSmith 降級策略

若環境已有 LANGSMITH_API_KEY 或 LANGCHAIN_API_KEY，會建立 LangSmith Client 並送出追蹤。若沒有 API key，仍會使用 local tracing 模式包裹執行，至少保留程式內一致的 LangSmith 追蹤介面與本機 log。

5. 模組名稱衝突處理

由於需求指定腳本名稱為 langsmith.py，執行時會和第三方套件 langsmith 同名。實作中會先暫時將腳本目錄從 sys.path 移除，再 import 真正的 langsmith 套件，避免 import 到自己。

## 實作重點

- 新增 Index/langsmith.py
- 預設讀取 Index/config-langsmith.txt
- 預設輸出 Index/log-langsmith.txt
- 若使用者不是用 .venv 的 Python 啟動 langsmith.py，腳本會先自動重新以專案 .venv 重新啟動自己
- execute 若指向 .py 檔，會自動改用目前的 sys.executable 啟動，避免跑到錯誤的 Python 環境
- 以兩個 reader thread 分別讀取 stdout 與 stderr，保留接近即時的輸出順序

## 驗證方式

在專案根目錄啟用虛擬環境後執行：

python Index/langsmith.py

成功條件：

- Index/log-langsmith.txt 產生
- 檔案中包含 return_code 與 LangSmith 區塊
- req-rrf.py 的 stdout 或 stderr 被寫入 log

## 已知前提

- req-rrf.py 仍依賴既有的 Chroma、hnswlib、Ollama 與索引資料
- 若未安裝 langsmith 套件，langsmith.py 會在 log 中記錄 import_error，且不會送出遠端追蹤