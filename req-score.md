# req-score.py 建置紀錄

## 目標

- 建立 Index/req-score.py。
- 使用 Index/config-req-score.txt 作為參數檔。
- 查詢 Index/db/data.db 中的向量資料。
- 讀取 Index/db/chapter-index.json 將 chunk 對應到章節。
- 將回答與 RAG Top 4 命中結果輸出到 Index/output.txt。

## 參考來源

- 參考 Pdf2Embedding/rag-request.py 的設定解析、Ollama embedding 查詢與生成回答流程。
- 參考 Index/index.py 與 Index/db/chapter-index.json 的 chunk_id / chapter 對應格式。

## 實作內容

1. 新增可同時支援 key=value 與 key:value 的設定解析，因為 Index/config-req-score.txt 的 question 使用冒號格式。
2. 讀取參數檔中的 question、model、embedding_model、base_url、collection、database_path、top_k、timeout。
3. 使用 Ollama embedding API 產生問題向量，並查詢 ChromaDB 取得 top_k 結果。
4. 查詢結果包含 documents、metadatas、distances，並用 chunk_id 對照 chapter-index.json 補上章節資訊。
5. 以 top 4 命中內容組成 prompt，向 Ollama 取得最終回答。
6. 將問題、回答、top 4 片段、距離分數與 JSON payload 寫入 Index/output.txt。

## 輸出內容

- 問題原文
- 模型回答
- RAG Top 4 命中結果
- 每筆命中的 chunk_id、distance、頁碼、章節名稱、章節預覽、內容
- 完整 JSON 結果，便於後續檢查或程式處理

## 驗證方式

- 執行 python Index/req-score.py
- 確認 Index/output.txt 已產生
- 確認 Index/output.txt 內含回答、Top 4 結果與向量距離分數