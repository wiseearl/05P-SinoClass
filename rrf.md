# RRF 混和索引建置記錄

## 目標

在 Index 目錄新增 req-rrf.py，讀取 config-rrf.txt，整合 chapter-index.json 與 hnsw-manifest.json 兩條召回路徑，透過 Reciprocal Rank Fusion, RRF 產生最終前 4 筆結果，並將答案與各路徑前 4 筆內容輸出到 output-rrf.txt。

## 設計選擇

1. chapter-index 路徑

使用既有的 Chroma collection 做語意檢索，並以 chapter-index.json 補上 chunk 對應章節資訊。這條路徑保留原本 chapter 索引的章節語境優勢。

2. hnsw 路徑

載入 db/hnsw-index.bin，並以 hnsw-manifest.json 提供 label 與 chunk_id 對應，再回到 Chroma 取回 chunk 原文與 metadata。這條路徑直接走 HNSW ANN 搜尋。

3. RRF 合併

對兩條結果各自以排名計算分數：

RRF score = Σ 1 / (k + rank)

預設 k 使用 60，可由 config-rrf.txt 的 rrf_k 覆寫。若同一 chunk 同時被兩條路徑命中，分數會累加。

4. 輸出內容

output-rrf.txt 會包含：

- 最後問題答案
- chapter-index Top 4
- hnsw-manifest Top 4
- RRF Top 4
- 每筆 chunk 的內容、分數、距離與來源排名
- 附加 JSON 便於後續比對或程式處理

## 實作重點

- 沿用現有查詢腳本的 config 解析、Ollama embedding、Ollama generate 與錯誤處理方式，避免不同腳本行為分歧。
- HNSW 查詢只依賴現有的 hnsw-index.bin 與 hnsw-manifest.json，不新增新的索引建置步驟。
- 兩條召回都統一以 chunk_id 為合併鍵，減少去重與對應成本。
- chapter 與 hnsw 原始結果皆保留 cosine distance 與換算後的 score = 1 - distance，RRF 則保留融合分數與來源排名。

## 執行方式

在專案根目錄啟用虛擬環境後執行：

python Index/req-rrf.py

或在 Index 目錄執行：

python req-rrf.py

## 相依條件

- Index/db/data.db
- Index/db/chapter-index.json
- Index/db/hnsw-index.bin
- Index/db/hnsw-manifest.json
- Ollama API 可用
- config-rrf.txt 內至少提供 question

## 驗證重點

- 能成功讀到兩份索引資料
- 能產生 chapter、hnsw、rrf 三組 Top 4
- 能使用 RRF Top 4 成功生成最終答案
- output-rrf.txt 內容包含題目、答案、chunk 內容與分數# RRF 混和索引建置紀錄

## 目標

在 Index 目錄下新增 req-rrf.py，讀取 config-rrf.txt，結合 chapter-index.json 與 hnsw-manifest.json 兩條查詢路徑，使用 Reciprocal Rank Fusion, RRF 合併排名，並將答案與三組 Top 4 結果輸出到 output-rrf.txt。

## 既有基礎

- req-score.py 已具備：設定檔解析、Ollama embedding、Chroma 查詢、答案生成、結果輸出。
- req-rerank.py 已具備：多階段召回後再排序的輸出格式。
- chapter-index.json 提供 chunk_id 對應章節資訊。
- hnsw-manifest.json 提供 HNSW label 與 chunk_id、metadata 的對照。
- hnsw-index.bin 已存在，可直接由 hnswlib 載入查詢。

## 設計決策

1. chapter 路徑

使用與 req-score.py 相同的 Chroma query 流程，依問題 embedding 查出 Top K chunk，並補上 chapter-index.json 的章節資訊。

2. hnsw 路徑

載入 hnsw-index.bin 與 hnsw-manifest.json，對問題 embedding 執行 knn_query，取得 label 後再映射成 chunk_id，最後回到 Chroma 取出文件內容。

3. RRF 合併

對 chapter 與 hnsw 兩組排序結果，以下式計算融合分數：

$$
RRF(d) = \sum_i \frac{1}{k + rank_i(d)}
$$

其中預設 $k = 60$，可由 config-rrf.txt 以 rrf_rank_constant 或 rrf_k 覆寫。

4. 輸出內容

output-rrf.txt 內容包含：

- 最後問題的答案
- chapter-index Top 4 chunk 內容與分數
- hnsw-manifest Top 4 chunk 內容與分數
- RRF Top 4 chunk 內容與分數
- JSON 區塊，保留機器可讀結果

## 實作重點

- 預設讀取：Index/config-rrf.txt
- 預設輸入：Index/db/chapter-index.json、Index/db/hnsw-manifest.json、Index/db/hnsw-index.bin、Index/db/data.db
- 預設輸出：Index/output-rrf.txt
- 保留與現有腳本一致的 Ollama /api/embed 與 /api/generate 呼叫模式
- generate 階段設定 think=false，避免 qwen 類模型回傳空結果

## 驗證方式

在專案根目錄啟用虛擬環境後執行：

python Index/req-rrf.py

成功條件：

- Index/output-rrf.txt 產生
- 檔案中同時出現 Chapter-Index Top 4、HNSW-Manifest Top 4、RRF Top 4 三個區塊
- 回答區塊有最終答案

## 可能風險

- 若 hnsw-index.bin 與 hnsw-manifest.json 不是同一批資料生成，label 對映會失真。
- 若 Chroma collection 名稱與 config 不一致，程式會退回第一個 collection。
- 若 Ollama 未啟動或指定模型不存在，腳本會直接失敗。