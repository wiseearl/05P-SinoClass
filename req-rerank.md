# req-rerank.py 建置紀錄

## 目標

- 建立 Index/req-rerank.py。
- 使用 Index/config-req-rerank.txt 作為參數檔。
- 查詢 Index/db/data.db 中的向量資料。
- 讀取 Index/db/chapter-index.json 將 chunk 對應到章節。
- 先取 level1 top 20，再以向量 cosine similarity 做 level2 top 4 rerank。
- 將回答與兩階段結果輸出到 Index/output-rerank.txt。

## 參考來源

- 參考 Index/req-score.py 的設定解析、Ollama embedding 取得、回答生成與輸出格式。
- 參考 Index/index.py 與 Index/db/chapter-index.json 的 chunk_id / chapter 對應格式。

## 實作內容

1. 延用 req-score.py 的設定解析，保留同時支援 key=value 與 key:value。
2. 讀取參數檔中的 question、model、embedding_model、base_url、collection、database_path、index_path、output、level1_top_k、level2_top_k、timeout。
3. 先用問題向量查詢 ChromaDB，取得 level1 top 20 候選 documents、metadatas、distances。
4. 針對 level1 候選 chunk_id，再由 ChromaDB 取回 embeddings，與問題向量計算 cosine similarity。
5. 依 rerank 分數排序，取 level2 top 4 作為最終上下文，送入 Ollama 生成答案。
6. 將問題、回答、level1 結果、level2 向量比對分數與 JSON payload 寫入 Index/output-rerank.txt。

## 輸出內容

- 問題原文
- 模型回答
- RAG Level 1 Top 20 結果
- RAG Level 2 Top 4 向量比對結果
- 每筆命中的 chunk_id、distance、rerank_score、頁碼、章節名稱、內容
- 完整 JSON 結果，便於後續檢查或程式處理

## 驗證方式

- 執行 python Index/req-rerank.py
- 確認 Index/output-rerank.txt 已產生
- 確認輸出內含 Level 1 Top 20 與 Level 2 Top 4 的分數與回答

## 本次執行紀錄

- 使用參數檔 Index/config-req-rerank.txt 中的問題：第一部內容摘要
- 執行指令：python Index/req-rerank.py
- 實際載入資料：Index/db/data.db 與 Index/db/chapter-index.json
- 執行結果：成功完成 level1 top 20 檢索與 level2 top 4 rerank
- 輸出檔案：Index/output-rerank.txt